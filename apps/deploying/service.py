"""Деплой: собрать, положить на сервер, проверить.

Сценарий 3 ТЗ п.16.5: сайт работает на серверах заказчика, управляется
через AuraBuilder. Здесь происходит ровно загрузка файлов и проверка
результата.

Чего деплой не делает и почему это правильно: он не запускает процессы
на чужом сервере. По FTP команды выполнять нельзя, а обход этого через
«как-нибудь» означал бы либо дыру в безопасности, либо зависимость от
закрытого API каждого хостинга. Запуск рантайма остаётся за
заказчиком, и инструкция кладётся рядом с файлами.

Порядок работы выбран один: сначала файлы сайта, потом рантайм, потом
проверка по HTTP. Проверка идёт последней, потому что раньше она всё
равно показала бы старый сайт.
"""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

from projects.package import RUNTIME_PROTOCOL_VERSION as PROTOCOL_VERSION

from .models import HostingProfile
from .runtime_pack import runtime_files
from .transports import DeployError, build_transport

# Файлы, которые остаются на сервере от прошлых деплоев: их нельзя
# считать мусором. Рантайм хранит там состояние магазина.
KEEP_ON_SERVER = ('.aurabuilder/', 'runtime/data/')

@dataclass
class DeployResult:
    ok: bool
    profile: str
    files_uploaded: int = 0
    files_removed: int = 0
    runtime_files: int = 0
    site_url: str = ''
    checks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    started_at: str = ''
    finished_at: str = ''

    def as_dict(self) -> dict:
        return {
            'ok': self.ok,
            'profile': self.profile,
            'filesUploaded': self.files_uploaded,
            'filesRemoved': self.files_removed,
            'runtimeFiles': self.runtime_files,
            'siteUrl': self.site_url,
            'checks': self.checks,
            'warnings': self.warnings,
            'startedAt': self.started_at,
            'finishedAt': self.finished_at,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalise_url(url: str) -> str:
    raw = (url or '').strip()
    if not raw:
        return ''
    if not raw.startswith(('http://', 'https://')):
        raw = f'https://{raw}'
    return raw.rstrip('/')


def _check(url: str, name: str, expect_ready: bool = False) -> dict:
    """Одна проверка по HTTP. Ошибка сети — это результат, а не
    исключение: пользователю нужно знать, что именно не открылось."""
    result = {'name': name, 'url': url, 'ok': False, 'detail': ''}
    if not url:
        result['detail'] = 'адрес не указан'
        return result
    try:
        request = urllib.request.Request(
            url, headers={'User-Agent': 'AuraBuilder-deploy-check'}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode('utf-8', 'replace')
            result['ok'] = response.status == 200
            if expect_ready:
                payload = json.loads(body)
                version = payload.get('protocolVersion')
                ready = payload.get('ready') is True
                # Клиент не подключается при несовпадении версий, и
                # деплой должен говорить об этом так же: файлы загружены,
                # а три модуля работать не будут.
                result['ok'] = result['ok'] and ready and version == PROTOCOL_VERSION
                if not ready:
                    result['detail'] = 'рантайм не настроен'
                elif version != PROTOCOL_VERSION:
                    result['detail'] = (
                        f'на сервере протокол {version}, '
                        f'а пакет собран под {PROTOCOL_VERSION}'
                    )
                else:
                    result['detail'] = f'рантайм готов, версия {version}'
            else:
                result['detail'] = f'HTTP {response.status}, {len(body)} байт'
    except (urllib.error.URLError, OSError) as exc:
        result['detail'] = f'не открывается: {exc}'
    except (json.JSONDecodeError, ValueError):
        result['detail'] = 'ответ не является JSON'
    return result


def deploy(
    project,
    version,
    profile: HostingProfile,
    *,
    site_key: str | None = None,
    verify: bool = True,
    rotate_key: bool = False,
) -> DeployResult:
    """Выкладывает версию проекта на хостинг по профилю."""
    from projects.package import build_package

    started = _now()
    site_url = _normalise_url(profile.site_url)
    result = DeployResult(
        ok=False, profile=profile.name, site_url=site_url, started_at=started
    )

    if not site_url:
        result.warnings.append(
            'Адрес сайта не задан: результат нельзя проверить. Заполните '
            'поле «Адрес сайта» в профиле.'
        )

    built = build_package(project, version, base_url=site_url)
    files: dict[str, str] = dict(built['files'])

    # Ключ установки живёт в профиле, а не вычитывается с сервера:
    # чтение файла обратным каналом означало бы, что деплой падает из-за
    # того, что сервер временно недоступен для чтения. Прежние cookie
    # покупателей при этом не перестают подходить.
    key = site_key or profile.site_key
    if rotate_key or not key:
        key = secrets.token_urlsafe(18)
    profile.site_key = key
    profile.save(update_fields=['site_key', 'updated_at'])
    endpoint = f'{site_url}/api/runtime' if site_url else ''
    files['runtime.json'] = json.dumps(
        {'version': PROTOCOL_VERSION, 'endpoint': endpoint, 'siteKey': key},
        ensure_ascii=False,
        indent=2,
    )

    transport = build_transport(profile)
    try:
        existing = set(transport.existing())
        uploaded = 0
        for name, content in files.items():
            transport.put(name, content.encode('utf-8'))
            uploaded += 1

        removed = _remove_stale(transport, existing - set(files))
        result.files_uploaded = uploaded
        result.files_removed = removed

        # Каталог рантайма — относительный: абсолютный путь профиля
        # сложился бы с корнем сайта повторно.
        runtime_dir = profile.runtime_relative_path
        pack = runtime_files(
            project_name=project.name,
            domain=urlparse(site_url).netloc if site_url else '',
            site_key=key,
            path=runtime_dir,
        )
        for name, content in pack.items():
            transport.put(f'{runtime_dir}/{name}', content.encode('utf-8'))
        result.runtime_files = len(pack)

        result.warnings.append(
            'Рантайм не запущен: по FTP команды на сервере не выполняются. '
            f'Выполните на сервере `sh {runtime_dir}/run.sh` '
            'или запустите службу по инструкции из README.'
        )
    except DeployError as exc:
        transport.close()
        result.warnings.append(str(exc))
        result.finished_at = _now()
        return result
    finally:
        try:
            transport.close()
        except Exception:  # noqa: BLE001 — закрытие не должно ронять деплой
            pass

    if verify and site_url:
        result.checks.append(_check(site_url, 'Главная страница'))
        result.checks.append(
            _check(f'{endpoint}/health', 'Рантайм отвечает', expect_ready=True)
        )
        if not all(check['ok'] for check in result.checks):
            result.warnings.append(
                'Проверка не прошла: файлы загружены, но сайт или рантайм '
                'пока не отвечают. Обычно это значит, что рантайм ещё '
                'не запущен или nginx не перезагружен.'
            )

    result.ok = not any(not check['ok'] for check in result.checks)
    result.finished_at = _now()
    return result


def _remove_stale(transport, stale: set[str]) -> int:
    """Убирает файлы прошлой сборки, которых больше нет в пакете.

    Без этого старый index.html остался бы на сервере, и сайт
    показывал бы предыдущую версию при полностью успешной загрузке.
    """
    removed = 0
    for name in sorted(stale):
        if any(name.startswith(keep) for keep in KEEP_ON_SERVER):
            continue
        # Каталог вроде assets/css не удаляется: лишняя пустая папка
        # безвредна, а обход по FTP стоит дороже, чем польза.
        if not name.count('/') and name.startswith('.'):
            continue
        try:
            transport.remove(name)
            removed += 1
        except DeployError:
            continue
    return removed


__all__ = ['DeployResult', 'deploy']
