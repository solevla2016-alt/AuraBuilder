"""Публикация: собрать, разложить, переключить, отозвать.

Порядок операций выбран по одному правилу: посетитель сайта никогда
не должен увидеть половину сборки. Поэтому новая версия сначала
пишется в отдельную папку целиком, и только потом становится текущей;
отзыв убирает сайт из раздачи раньше, чем удаляет файлы.

Ещё одно: переключение версии — это запись в таблице и чтение папки по
имени из неё, а не симлинк. Симлинк не работает на Windows и на
части хостингов, а публикация должна вести себя одинаково везде.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.db import transaction

from projects.package import PackageTooLarge, build_package

from .models import (
    STATE_ACTIVE,
    STATE_WITHDRAWN,
    Backup,
    Site,
    SiteVersion,
    publish_root,
    slugify_site_name,
)

#: Сколько последних версий хранится на диске. Хранение всех версий
#: съедало бы место, которого у файловой публикации нет.
KEEP_VERSIONS = 5

#: Сколько резервных копий хранится (ТЗ п.16.3 — ежедневные копии).
KEEP_BACKUPS = 7


class PublishError(Exception):
    """Публикация не удалась. Текст идёт в интерфейс."""


class SiteNotFound(Exception):
    """По адресу нет сайта, или он отозван."""


@dataclass
class PublishResult:
    site: Site
    version: SiteVersion
    files: int
    size: int
    url: str
    warnings: list[str]


def _free_slug(base: str) -> str:
    candidate = base
    index = 2
    while Site.objects.filter(slug=candidate).exists():
        candidate = f'{base}-{index}'
        index += 1
    return candidate


def _write_tree(files: dict[str, str], directory: Path) -> tuple[int, int]:
    """Пишет файлы сборки и возвращает их количество и размер."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    total = 0
    count = 0
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode('utf-8') if isinstance(content, str) else content
        target.write_bytes(data)
        total += len(data)
        count += 1
    return count, total


@transaction.atomic
def publish(project, version, slug: str | None = None) -> PublishResult:
    """Публикует версию проекта и делает её текущей."""

    if version is None:
        raise PublishError('Сначала сохраните проект: нечего публиковать.')

    base = slugify_site_name(slug or project.name)
    site = Site.objects.filter(project=project).first()
    if site is None:
        site = Site.objects.create(
            project=project, slug=_free_slug(base), state=STATE_ACTIVE
        )
    elif slug and slugify_site_name(slug) != site.slug:
        raise PublishError(
            f'Адрес сайта уже задан: {site.slug}. Смена адреса — отдельная '
            'операция, чтобы старые ссылки не перестали работать молча.'
        )

    # Повторная публикация той же версии: файлы не пересобираются.
    existing = site.versions.filter(number=version.number).first()
    if existing is not None and site.current_version_id == existing.id:
        if not site.is_active:
            # Отзыв обратим: повторная публикация возвращает сайт в
            # работу, иначе пришлось бы выпускать новую версию ради
            # одного и того же содержимого.
            site.state = STATE_ACTIVE
            site.withdrawn_at = None
            site.save(update_fields=['state', 'withdrawn_at'])
        return PublishResult(
            site=site, version=existing, files=existing.files,
            size=existing.size, url=site.url(),
            warnings=['Эта версия уже опубликована: файлы не пересобирались.'],
        )

    try:
        built = build_package(project, version, base_url=site.url())
    except PackageTooLarge as exc:
        raise PublishError(f'Проект не публикуется: превышен лимит ({exc}).') from exc

    relative = f'sites/{site.slug}/versions/v{version.number}-{version.number:04d}'
    target = publish_root() / relative
    files, size = _write_tree(built['files'], target)

    published = site.versions.create(
        number=version.number, path=relative, size=size, files=files
    )
    site.current_version = published
    site.state = STATE_ACTIVE
    site.withdrawn_at = None
    site.published_at = timezone_now()
    site.save(update_fields=['current_version', 'state', 'withdrawn_at',
                             'published_at'])

    _prune_versions(site)
    return PublishResult(
        site=site,
        version=published,
        files=files,
        size=size,
        url=site.url(),
        warnings=list(built['report'].warnings),
    )


def timezone_now():
    from django.utils import timezone

    return timezone.now()


@transaction.atomic
def withdraw(site: Site, remove_files: bool = False) -> None:
    """Отзывает публикацию.

    Файлы по умолчанию остаются: отзыв обратим, и удаление сайта по
    одной кнопке — плохая идея. Версии, отозванные дольше месяца,
    удаляются плановой задачей.
    """
    site.state = STATE_WITHDRAWN
    site.withdrawn_at = timezone_now()
    site.save(update_fields=['state', 'withdrawn_at'])

    if remove_files:
        directory = site.directory()
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)


def _prune_versions(site: Site) -> None:
    """Оставляет последние KEEP_VERSIONS версий, прочее удаляет.

    Текущая версия не удаляется никогда: иначе отзыв с ошибкой
    оставил бы сайт без файлов.
    """
    keep = {site.current_version_id}
    for version in site.versions.order_by('-number')[:KEEP_VERSIONS]:
        keep.add(version.id)
    for version in site.versions.exclude(id__in=keep):
        directory = version.directory
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        version.delete()


def backup_site(site: Site, now: datetime | None = None) -> Backup | None:
    """Делает резервную копию текущей публикации (ТЗ п.16.3).

    Копия снимком байтов, а не ссылкой: восстановление из ссылки не
    восстановило бы ничего, если файлы удалены.
    """
    if site.current_version is None:
        return None
    stamp = (now or datetime.now(UTC)).strftime('%Y%m%d-%H%M%S')
    relative = f'sites/{site.slug}/backups/v{site.current_version.number}-{stamp}'
    target = publish_root() / relative
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(site.current_version.directory, target)

    size = sum(f.stat().st_size for f in target.rglob('*') if f.is_file())
    backup, _ = Backup.objects.update_or_create(
        site=site,
        number=site.current_version.number,
        defaults={'path': relative, 'size': size},
    )
    _prune_backups(site)
    return backup


def _prune_backups(site: Site) -> None:
    for backup in site.backups.order_by('-created_at')[KEEP_BACKUPS:]:
        directory = backup.directory
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        backup.delete()


def resolve(slug: str, path: str = '') -> tuple[SiteVersion, Path]:
    """Находит папку текущей версии по адресу.

    Отозванный сайт отдаёт 410, а не 404: разница видна посетителю и
    владельцу — сайт был и был отозван, а не никогда не существовал.
    """
    site = Site.objects.filter(slug=slug).first()
    if site is None:
        raise SiteNotFound('Сайт не найден')
    if not site.is_active:
        raise SiteNotFound('Сайт отозван')
    if site.current_version is None:
        raise SiteNotFound('У сайта нет опубликованной версии')

    root = site.current_version.directory.resolve()
    target = (root / path.lstrip('/')).resolve() if path else root
    if not str(target).startswith(str(root)):
        # Выход за пределы папки сайта: путь вида ../../secret не должен
        # приводить к чтению чужих файлов.
        raise SiteNotFound('Файл не найден')
    if target.is_dir():
        target = target / 'index.html'
    if not target.is_file():
        raise SiteNotFound('Файл не найден')
    return site.current_version, target


def note_request(site: Site) -> None:
    """Считает обращения: по ним видно, жив ли сайт (мониторинг)."""
    from django.utils import timezone

    Site.objects.filter(pk=site.pk).update(
        requests=site.requests + 1, last_request_at=timezone.now()
    )
    site.requests += 1


def checksum(directory: Path) -> str:
    """Контрольная сумма содержимого папки.

    Нужна для ответа «тот ли сайт лежит на диске»: без неё сравнение
    папок возможно только вручную.
    """
    digest = hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(directory)).encode('utf-8'))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def status_payload(site: Site) -> dict:
    """Состояние публикации для интерфейса."""
    return {
        'slug': site.slug,
        'url': site.url(),
        'state': site.state,
        'active': site.is_active,
        'publishedAt': site.published_at.isoformat() if site.published_at else None,
        'withdrawnAt': (
            site.withdrawn_at.isoformat() if site.withdrawn_at else None
        ),
        'currentVersion': (
            site.current_version.public_dict() if site.current_version else None
        ),
        'versions': [v.public_dict() for v in site.versions.all()[:KEEP_VERSIONS]],
        'requests': site.requests,
        'lastRequestAt': (
            site.last_request_at.isoformat() if site.last_request_at else None
        ),
        'backups': site.backups.count(),
    }


__all__ = [
    'PublishError',
    'PublishResult',
    'SiteNotFound',
    'backup_site',
    'checksum',
    'note_request',
    'publish',
    'resolve',
    'status_payload',
    'withdraw',
]