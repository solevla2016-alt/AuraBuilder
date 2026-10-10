"""Сборка пакета: снимок версии → файлы → архив (ТЗ п.16.4).

Отдельный модуль от рендера: рендер отвечает на вопрос «как выглядит
блок», сборка — «что положить в архив и как это проверить». Проверки
живут здесь же, потому что их результат решает, будет ли пакет выдан:
проверять отдельно — значит забыть проверить (п.16.2: артефакт либо
валиден целиком, либо задание неуспешно).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from django.conf import settings

from component_library.models import ComponentStyle

from data_sources.models import DataSource

from .export import (
    FORBIDDEN_HOSTS,
    FORMAT_VERSION,
    RENDERERS,
    ExportError,
    build_css,
    esc,
    render_block,
    slugify,
)
from .models import DocumentVersion, Project

#: Предел размера архива, МБ. Число взято из тарифных лимитов (п.17.1)
#: для статики: сайт тяжелее этого почти наверняка содержит файлы,
#: которые надо сначала сжать.
MAX_ARCHIVE_MB = 100


@dataclass
class ValidationReport:
    """Результат проверок пакета перед выдачей."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def slugify_ascii(value: str) -> str:
    """Имя файла для HTTP-заголовка: только ASCII.

    Заголовок Content-Disposition ограничен ASCII, а кириллическое имя
    кодируется платформой как «=?utf-8?b?...?=» и в этом виде
    показывается пользователю. Транслитерация даёт «magazin-cvetov».
    """

    table = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '',
        'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    out: list[str] = []
    for ch in value.lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
        else:
            out.append(table.get(ch, '-'))
    slug = ''.join(out)
    while '--' in slug:
        slug = slug.replace('--', '-')
    return slug.strip('-') or 'project'


def _page_html(project_name: str, body: str, title: str, description: str) -> str:
    """Страница пакета.

    lang="ru" и charset заданы сразу: без них русский текст в браузере
    разъезжается, а это первое, на что смотрит заказчик.
    """

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
<meta name="generator" content="AuraBuilder">
<link rel="stylesheet" href="assets/css/site.css">
</head>
<body>
<main class="page">
{body}
</main>
</body>
</html>
"""


def _records_for(block: dict, sources: dict[str, list[dict]]) -> list[dict]:
    """Записи источника для блока данных."""

    props = block.get('props')
    source_id = props.get('source') if isinstance(props, dict) else None
    if not isinstance(source_id, str) or not source_id:
        return []
    return sources.get(source_id, [])


class PackageTooLarge(Exception):
    """Выгрузка не укладывается в технический лимит (ТЗ п.4.11)."""


def _collect_sources(project: Project, version: DocumentVersion) -> dict[str, list[dict]]:
    """Данные источников, на которые ссылается снимок.

    Берутся только те источники, что упомянуты в дереве: выгружать все
    источники проекта значило бы положить в архив данные, до которых
    страница не дтягивается.

    Записи берутся целиком. Раньше здесь стоял срез [:100], и источник
    со 150 записями молча терял 50 из них: архив получался
    корректным, сборка проходила, и потеря обнаруживалась только на
    опубликованном сайте. Обрезать данные молча нельзя, поэтому
    превышение лимита останавливает выгрузку с внятным сообщением.
    """

    referenced: set[str] = set()
    for block in (version.tree or {}).get('blocks', []):
        props = block.get('props')
        if isinstance(props, dict):
            source = props.get('source')
            if isinstance(source, str) and source:
                referenced.add(source)

    out: dict[str, list[dict]] = {}
    if not referenced:
        return out
    limit = settings.LIMITS['MAX_RECORDS_PER_SOURCE']
    for data_source in DataSource.objects.filter(project=project, id__in=referenced):
        total = data_source.records.count()
        if total > limit:
            raise PackageTooLarge(
                f'источник «{data_source.name}»: записей {total}, максимум {limit}'
            )
        rows = []
        for record in data_source.records.all():
            values = record.data if isinstance(record.data, dict) else {}
            rows.append(' · '.join(str(v) for v in values.values() if v not in (None, '')))
        out[str(data_source.id)] = rows
    return out


def _component_styles(project_id: Any) -> dict[str, dict]:
    """Стили видов компонентов проекта.

    Фильтр по идентификатору, а не по объекту: Django не принимает
    несохранённый экземпляр в условии related-поля, а сборка всегда
    идёт по сохранённому проекту.
    """

    if not project_id:
        return {}
    return {s.kind: s.tokens for s in ComponentStyle.objects.filter(project_id=project_id)}


def _robots_txt(base_url: str) -> str:
    lines = ['User-agent: *', 'Allow: /']
    if base_url:
        lines.append(f'Sitemap: {base_url.rstrip("/")}/sitemap.xml')
    return '\n'.join(lines) + '\n'


def _sitemap_xml(base_url: str, pages: list[str]) -> str:
    root = base_url.rstrip('/')
    urls = '\n'.join(
        f'  <url><loc>{esc(root + "/" + path)}</loc></url>' for path in pages
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>
"""


def _readme(project_name: str, manifest: dict) -> str:
    return f"""# {project_name}

Сайт собран в AuraBuilder. Архив статический: сервер AuraBuilder для его
работы не нужен.

## Как разместить

1. Распакуйте архив в каталог сайта на хостинге (Timeweb, Beget,
   Selectel, Reg.ru, SpaceWeb, First VDS).
2. Убедитесь, что `index.html` лежит в корне. Для каталогов
   используется `index.html`, чтобы адрес оканчивался слэшем.
3. Всё. Статический сайт не требует Node.js, базы данных и сборки на
   сервере.

## Что внутри

| Файл | Назначение |
|------|-----------|
| `index.html` | Главная страница |
| `assets/css/site.css` | Стили, собранные из палитры проекта |
| `build-manifest.json` | Версия документа, состав сборки, контрольные суммы |
| `robots.txt`, `sitemap.xml` | Файлы для поисковиков |

## Сборка

- Проект: {project_name}
- Версия документа: {manifest['documentVersion']}
- Версия зафиксирована: {manifest['builtAt']}
- Блоков на странице: {manifest['blocks']}

Повторная сборка той же версии даёт тот же результат: внешние ссылки не
используются, время сборки меняется, но контрольные суммы файлов — нет.
"""


def validate_files(files: dict[str, str], base_url: str = '') -> ValidationReport:
    """Проверки перед выдачей архива (ТЗ п.16.4).

    Порядок не важен, набор фиксированный: пропущенная проверка — это
    пакет, который уедет к заказчику и упадёт там.
    """

    report = ValidationReport()

    for host in FORBIDDEN_HOSTS:
        for name, content in files.items():
            if host in content:
                report.errors.append(
                    f'{name}: внешняя ссылка на {host} (п.15.3, п.16.4)'
                )

    if 'index.html' not in files:
        report.errors.append('нет index.html')

    for name in ('robots.txt', 'sitemap.xml', 'build-manifest.json'):
        if name not in files:
            report.errors.append(f'нет {name}')

    html_files = [name for name in files if name.endswith('.html')]
    if not html_files:
        report.errors.append('в пакете нет ни одной HTML-страницы')
    for name in html_files:
        content = files[name]
        if '<html' not in content or '</html>' not in content:
            report.errors.append(f'{name}: страница не закрыта')
        if 'charset="utf-8"' not in content and "charset='utf-8'" not in content:
            report.errors.append(f'{name}: не задан charset — русский текст разъедется')
        if 'og:title' not in content:
            report.warnings.append(f'{name}: нет Open Graph-тегов')

    total = sum(len(c.encode('utf-8')) for c in files.values())
    if total > MAX_ARCHIVE_MB * 1024 * 1024:
        report.errors.append(f'архив тяжелее {MAX_ARCHIVE_MB} МБ')

    return report


def build_package(project: Project, version: DocumentVersion, base_url: str = '') -> dict:
    """Файлы пакета и манифест. Бросает ExportError при сбое."""

    tree = version.tree if isinstance(version.tree, dict) else {}
    blocks = tree.get('blocks')
    if not isinstance(blocks, list):
        raise ExportError('В версии нет дерева страницы.')

    sources = _collect_sources(project, version)
    styles = _component_styles(getattr(project, 'id', None))

    rendered = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ExportError('Блок описан неверно.')
        module_id = str(block.get('module', ''))
        # Записи нужны и data.*, и коммерческим блокам: каталог и
        # карточка товара читают тот же источник, что и узел данных.
        wants_records = module_id.startswith(('data.', 'shop.', 'promo.'))
        records = _records_for(block, sources) if wants_records else []
        rendered.append(render_block(block, records))

    body = '\n'.join(r.html for r in rendered)
    title = project.name
    html_files = {
        'index.html': _page_html(
            project.name,
            body,
            title,
            f'{project.name} — сайт, собранный в AuraBuilder',
        )
    }

    files: dict[str, str] = {
        'assets/css/site.css': build_css(styles),
        'robots.txt': _robots_txt(base_url),
        'sitemap.xml': _sitemap_xml(base_url, ['index.html']),
    }

    # Данные кладутся отдельным файлом: страница подключает их через
    # data-* атрибуты, и без платформы их больше негде взять.
    if sources:
        files['assets/data/data.json'] = json.dumps(
            {key: values for key, values in sources.items()},
            ensure_ascii=False,
            indent=2,
        )

    checksums = {
        name: hashlib.sha256(content.encode('utf-8')).hexdigest()
        for name, content in {**html_files, **files}.items()
    }

    manifest = {
        'formatVersion': FORMAT_VERSION,
        'project': {'id': str(project.id), 'name': project.name},
        'documentVersion': version.number,
        'snapshotId': str(version.id),
        # Время сборки — момент фиксации версии, а не «сейчас».
        # Иначе два экспорта одной версии отличались бы, а требование
        # п.16.2 («повторный экспорт той же версии даёт тот же
        # результат») перестало бы выполняться: сравнивать сборки было
        # бы нечем, и нельзя отличить изменение содержимого от того,
        # что кто-то пересобрал в другую минуту.
        'builtAt': version.created_at.isoformat() if version.created_at else None,
        'blocks': len(rendered),
        'modules': sorted({r.module_id for r in rendered}),
        'files': checksums,
        'externalDependencies': [],
        'requiresPlatform': False,
    }

    files['build-manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2)
    files['README.md'] = _readme(project.name, manifest)
    files.update(html_files)

    report = validate_files(files, base_url)
    if not report.ok:
        raise ExportError('; '.join(report.errors))

    manifest['warnings'] = report.warnings
    files['build-manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2)
    return {'files': files, 'manifest': manifest, 'report': report}


def package_zip(files: dict[str, str]) -> tuple[str, bytes]:
    """Архив из готовых файлов.

    Время в архиве фиксировано: без этого два экспорта одной версии
    отличались бы байтами, и сравнение сборок было бы невозможно.
    """

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name].encode('utf-8'))
    return '', buffer.getvalue()