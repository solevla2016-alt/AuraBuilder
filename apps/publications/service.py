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
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from projects.events import record
from projects.models import ProjectEvent
from projects.package import PackageTooLarge, build_package
from projects.package import FileContent, _as_bytes

from .models import (
    SCHEDULE_CANCELLED,
    SCHEDULE_DONE,
    SCHEDULE_FAILED,
    SCHEDULE_PENDING,
    STATE_ACTIVE,
    STATE_WITHDRAWN,
    Backup,
    ScheduledPublication,
    Site,
    SiteVersion,
    publish_root,
    slugify_site_name,
)

logger = logging.getLogger(__name__)

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


def _write_tree(files: dict[str, FileContent], directory: Path) -> tuple[int, int]:
    """Пишет файлы сборки и возвращает их количество и размер.

    Картинки приходят байтами и пишутся как есть: перекодирование
    испортило бы файл, а на опубликованном сайте появились бы битые
    картинки при полностью «успешной» публикации.
    """
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    total = 0
    count = 0
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _as_bytes(content)
        target.write_bytes(data)
        total += len(data)
        count += 1
    return count, total


def _ensure_site(project, slug: str | None = None) -> Site:
    """Сайт проекта; создаётся при первой публикации или планировании."""
    base = slugify_site_name(slug or project.name)
    site = Site.objects.filter(project=project).first()
    if site is None:
        return Site.objects.create(
            project=project, slug=_free_slug(base), state=STATE_ACTIVE
        )
    if slug and slugify_site_name(slug) != site.slug:
        raise PublishError(
            f'Адрес сайта уже задан: {site.slug}. Смена адреса — отдельная '
            'операция, чтобы старые ссылки не перестали работать молча.'
        )
    return site


def build_site_version(site: Site, project, version) -> tuple[SiteVersion, list[str]]:
    """Собирает пакет версии, но не делает её текущей.

    Общая часть обычной и отложенной публикации. Файлы пишутся в
    отдельную папку, поэтому посетитель никогда не видит половину
    сборки. Уже собранная версия переиспользуется: повторное
    планирование не должно тратить время на те же файлы.
    """
    existing = site.versions.filter(number=version.number).first()
    if existing is not None and (existing.directory / 'index.html').is_file():
        return existing, ['Версия уже собрана: файлы не пересобирались.']

    try:
        built = build_package(project, version, base_url=site.url())
    except PackageTooLarge as exc:
        raise PublishError(f'Проект не публикуется: превышен лимит ({exc}).') from exc

    relative = f'sites/{site.slug}/versions/v{version.number}-{version.number:04d}'
    target = publish_root() / relative
    files, size = _write_tree(built['files'], target)

    if existing is not None:
        # Строка осталась, а папки нет: путь тот же, поэтому обновляем
        # размеры вместо второй записи с тем же номером версии.
        existing.size = size
        existing.files = files
        existing.save(update_fields=['size', 'files'])
        published = existing
    else:
        published = site.versions.create(
            number=version.number, path=relative, size=size, files=files
        )
    return published, list(built['report'].warnings)


def _activate(site: Site, published: SiteVersion, when=None) -> None:
    """Делает собранную версию текущей. Общая часть публикаций."""
    site.current_version = published
    site.state = STATE_ACTIVE
    site.withdrawn_at = None
    site.published_at = when or timezone_now()
    site.save(update_fields=['current_version', 'state', 'withdrawn_at',
                             'published_at'])


@transaction.atomic
def publish(project, version, slug: str | None = None) -> PublishResult:
    """Публикует версию проекта и делает её текущей."""

    if version is None:
        raise PublishError('Сначала сохраните проект: нечего публиковать.')

    site = _ensure_site(project, slug)

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

    published, warnings = build_site_version(site, project, version)
    _activate(site, published)
    _prune_versions(site)
    return PublishResult(
        site=site,
        version=published,
        files=published.files,
        size=published.size,
        url=site.url(),
        warnings=warnings,
    )


@transaction.atomic
def schedule_publication(project, version, when: datetime, user=None,
                         slug: str | None = None
                         ) -> tuple[ScheduledPublication, list[str]]:
    """Собирает версию сейчас и ставит её включение на указанное время.

    Сборка намеренно не откладывается: если файлы проекта пропадут или
    сборка перестанет укладываться в лимит, человек узнает об этом
    сразу, а не в момент, когда сайт должен был обновиться.
    """
    if version is None:
        raise PublishError('Сначала сохраните проект: нечего публиковать.')

    site = _ensure_site(project, slug)
    published, warnings = build_site_version(site, project, version)
    schedule = ScheduledPublication.objects.create(
        site=site,
        version_number=published.number,
        scheduled_at=when,
        created_by=(
            user if user is not None and user.is_authenticated else None
        ),
    )
    return schedule, warnings


def due_schedules(now: datetime | None = None):
    """Очередь отложенных публикаций, время которых наступило."""
    return (
        ScheduledPublication.objects
        .filter(
            state=SCHEDULE_PENDING,
            scheduled_at__lte=now or timezone_now(),
        )
        .select_related('site__project')
        .order_by('scheduled_at')
    )


@transaction.atomic
def cancel_schedule(schedule: ScheduledPublication) -> bool:
    """Отменяет ещё не выполненную публикацию. False — уже не ждёт."""
    finished = timezone_now()
    updated = ScheduledPublication.objects.filter(
        pk=schedule.pk, state=SCHEDULE_PENDING,
    ).update(state=SCHEDULE_CANCELLED, finished_at=finished)
    if updated:
        schedule.state = SCHEDULE_CANCELLED
        schedule.finished_at = finished
    return bool(updated)


def _finish_schedule(schedule: ScheduledPublication, state: str,
                     error: str, moment: datetime) -> None:
    schedule.state = state
    schedule.error = (error or '')[:300]
    schedule.finished_at = moment
    schedule.save(update_fields=['state', 'error', 'finished_at'])


def apply_due(now: datetime | None = None) -> list[ScheduledPublication]:
    """Включает все публикации, время которых наступило.

    Каждая публикация обрабатывается отдельно: сбой одной не должен
    задерживать остальные. Ошибка сохраняется в записи и попадает в
    журнал проекта — иначе неудачная отложенная публикация выглядела бы
    как «ничего не произошло».
    """
    moment = now or timezone_now()
    ids = list(due_schedules(moment).values_list('id', flat=True))
    applied: list[ScheduledPublication] = []

    for schedule_id in ids:
        try:
            with transaction.atomic():
                schedule = (
                    ScheduledPublication.objects
                    .select_for_update()
                    .select_related('site__project')
                    .filter(pk=schedule_id)
                    .first()
                )
                if schedule is None or schedule.state != SCHEDULE_PENDING:
                    continue

                site = Site.objects.select_for_update().get(
                    pk=schedule.site_id
                )
                version = site.versions.filter(
                    number=schedule.version_number
                ).first()
                if version is None or not (
                    version.directory / 'index.html'
                ).is_file():
                    _finish_schedule(
                        schedule, SCHEDULE_FAILED,
                        'Собранная версия удалена с диска: публиковать нечего.',
                        moment,
                    )
                    record(
                        schedule.site.project, ProjectEvent.KIND_SCHEDULE,
                        f'Отложенная публикация версии '
                        f'{schedule.version_number} не выполнена: '
                        'файлы версии удалены.',
                        status=ProjectEvent.STATUS_FAILED,
                    )
                    applied.append(schedule)
                    continue

                # Время публикации — запланированное, а не момент, когда
                # планировщик проснулся: при задержке таймера на минуту
                # отчёт не должен врать о дате выхода версии.
                _activate(site, version, when=schedule.scheduled_at)
                _finish_schedule(schedule, SCHEDULE_DONE, '', moment)
                _prune_versions(site)
                record(
                    schedule.site.project, ProjectEvent.KIND_SCHEDULE,
                    f'Отложенная публикация выполнена: версия '
                    f'{schedule.version_number}, {site.slug}.',
                    status=ProjectEvent.STATUS_OK, actor=schedule.created_by,
                )
                applied.append(schedule)
        except Exception as exc:  # noqa: BLE001 — одна публикация не роняет очередь
            logger.exception('отложенная публикация %s не выполнена',
                             schedule_id)
            ScheduledPublication.objects.filter(
                pk=schedule_id, state=SCHEDULE_PENDING,
            ).update(state=SCHEDULE_FAILED, error=str(exc)[:300],
                     finished_at=moment)
            failed = (
                ScheduledPublication.objects
                .select_related('site__project')
                .filter(pk=schedule_id)
                .first()
            )
            if failed is not None:
                record(
                    failed.site.project, ProjectEvent.KIND_SCHEDULE,
                    f'Отложенная публикация версии '
                    f'{failed.version_number} не выполнена: {exc}',
                    status=ProjectEvent.STATUS_FAILED,
                )
                applied.append(failed)

    return applied


def timezone_now():
    """Текущее время: одно место, чтобы отложенная публикация и отзыв
    считали время одинаково."""
    return timezone.now()


@transaction.atomic
def withdraw(site: Site, remove_files: bool = False) -> None:
    """Отзывает публикацию.

    Файлы по умолчанию остаются: отзыв обратим, и удаление сайта по
    одной кнопке — плохая идея.

    С удалением файлов удаляются и записи о версиях и копиях. Раньше
    каталог стирался, а строки в базе оставались: сайт помечался
    отозванным, но повторная публикация видела «уже опубликованную
    версию», файлы не пересобирала и возвращала сайт, состоящий из
    пустых ссылок на несуществующие файлы.
    """
    site.state = STATE_WITHDRAWN
    site.withdrawn_at = timezone_now()
    site.save(update_fields=['state', 'withdrawn_at'])

    # Отзыв отменяет и будущее включение. Иначе сайт, который владелец
    # убрал, вернулся бы сам в запланированное время, и человек узнал бы
    # об этом от посетителей.
    ScheduledPublication.objects.filter(
        site=site, state=SCHEDULE_PENDING,
    ).update(state=SCHEDULE_CANCELLED, finished_at=timezone_now())

    if remove_files:
        directory = site.directory()
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        # Записи без файлов вредны: по ним история показывает версии,
        # которых на диске нет, а публикация считает, что версия уже
        # выложена. Сначала снимается ссылка на текущую версию, иначе
        # удаление строк оставило бы её болтаться.
        Backup.objects.filter(site=site).delete()
        site.versions.all().delete()
        site.current_version = None
        site.save(update_fields=['current_version'])


def _prune_versions(site: Site) -> None:
    """Оставляет последние KEEP_VERSIONS версий, прочее удаляет.

    Текущая версия не удаляется никогда: иначе отзыв с ошибкой
    оставил бы сайт без файлов.
    """
    keep = {site.current_version_id}
    # Версии, на которые ссылаются отложенные публикации, тоже нельзя
    # удалять: к моменту срабатывания файлов уже не будет, и задание
    # провалится, хотя человек всё сделал правильно.
    scheduled_numbers = list(
        site.scheduled
        .filter(state=SCHEDULE_PENDING)
        .values_list('version_number', flat=True)
    )
    keep.update(
        site.versions
        .filter(number__in=scheduled_numbers)
        .values_list('id', flat=True)
    )
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

    Каждая копия — отдельная запись и отдельный каталог. Раньше запись
    обновлялась по номеру версии, из-за чего вторая копия того же дня
    заменяла первую, а её каталог оставался на диске навсегда: за
    месяц ежедневных копий накапливалось месяц недоступных папок.
    """
    if site.current_version is None:
        return None
    stamp = (now or datetime.now(UTC)).strftime('%Y%m%d-%H%M%S')
    relative = _free_backup_path(site, site.current_version.number, stamp)
    target = publish_root() / relative
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(site.current_version.directory, target)

    size = sum(f.stat().st_size for f in target.rglob('*') if f.is_file())
    backup = Backup.objects.create(
        site=site,
        number=site.current_version.number,
        path=relative,
        size=size,
    )
    _prune_backups(site)
    return backup


def _free_backup_path(site: Site, number: int, stamp: str) -> str:
    """Каталог копии, ещё не занятый другой копией.

    Отметка времени имеет секунды, а копирование по таймеру дважды за
    секунду вполне возможно. Без суффикса вторая копия удалила бы
    каталог первой, и обе записи в истории указывали бы на один и тот
    же путь.
    """
    base = f'sites/{site.slug}/backups/v{number}-{stamp}'
    taken = set(site.backups.values_list('path', flat=True))
    candidate = base
    index = 2
    while candidate in taken or (publish_root() / candidate).exists():
        candidate = f'{base}-{index}'
        index += 1
    return candidate


def _prune_backups(site: Site) -> None:
    for backup in site.backups.order_by('-created_at')[KEEP_BACKUPS:]:
        directory = backup.directory
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        backup.delete()


def restore_backup(site: Site, backup: Backup) -> SiteVersion:
    """Возвращает на место публикацию из резервной копии (ТЗ п.16.3).

    Копия кладётся на место своей версии, а текущей становится она.
    Так история остаётся правдивой: в ней по-прежнему видно, какая
    версия сколько занимает, а «восстановить» не значит «стереть
    следы». Файлы прошлых версий не трогаются.

    Отдельная новая запись не заводится намеренно: номер версии уже
    занят и менять его нельзя, а заводить дубликат значило бы показать
    в истории две седьмые версии.
    """
    source = backup.directory
    if not (source / 'index.html').is_file():
        raise PublishError(
            'Копия удалена с диска: восстанавливать нечего. Сделайте '
            'новую копию перед следующим откатом.'
        )

    # Освобождаем номер версии: запись и её каталог заменяются копией.
    stale = site.versions.filter(number=backup.number).first()
    if stale is not None:
        if site.current_version_id == stale.id:
            site.current_version = None
            site.save(update_fields=['current_version'])
        shutil.rmtree(stale.directory, ignore_errors=True)
        stale.delete()

    relative = f'sites/{site.slug}/versions/v{backup.number}-{backup.number:04d}'
    target = publish_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)

    files = sum(1 for item in target.rglob('*') if item.is_file())
    size = sum(item.stat().st_size for item in target.rglob('*') if item.is_file())
    version = SiteVersion.objects.create(
        site=site, number=backup.number, path=relative, size=size, files=files,
    )

    site.current_version = version
    site.state = STATE_ACTIVE
    site.withdrawn_at = None
    site.published_at = timezone_now()
    site.save(update_fields=[
        'current_version', 'state', 'withdrawn_at', 'published_at',
    ])
    return version


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
        'scheduled': [
            item.public_dict()
            for item in site.scheduled.filter(state=SCHEDULE_PENDING)[:20]
        ],
    }


__all__ = [
    'PublishError',
    'PublishResult',
    'SiteNotFound',
    'apply_due',
    'backup_site',
    'build_site_version',
    'cancel_schedule',
    'checksum',
    'due_schedules',
    'note_request',
    'publish',
    'resolve',
    'schedule_publication',
    'status_payload',
    'withdraw',
]