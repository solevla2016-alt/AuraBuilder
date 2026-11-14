"""API публикации: опубликовать, посмотреть состояние, отозвать.

Право — PUBLISH: публикация делает сайт доступным по адресу, и это
действие тарифов (ТЗ п.17.1), а не чтение проекта. Состояние
публикации видно всем, кто читает проект: «сайт опубликован, но не
работает» должно быть видно раньше, чем об этом узнает посетитель.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import PUBLISH, VIEW, ProjectAccess, can
from accounts.serializers import audit
from projects.events import record
from projects.models import DocumentVersion, Project, ProjectEvent

from .models import SCHEDULE_PENDING, Backup, ScheduledPublication, Site
from .service import (
    PublishError,
    backup_site,
    cancel_schedule,
    publish,
    restore_backup,
    schedule_publication,
    status_payload,
    withdraw,
)


def _project(project_id: str) -> Project | None:
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, TypeError):
        return None


@api_view(['GET', 'POST'])
@permission_classes([ProjectAccess])
def project_site(request, project_id: str):
    """Состояние публикации и публикация версии."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    site = Site.objects.filter(project=project).first()

    if request.method == 'GET':
        if site is None:
            return Response({'state': 'none', 'published': False},
                            status=status.HTTP_200_OK)
        return Response({'state': 'published', 'published': True,
                         **status_payload(site)})

    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Публиковать проект может тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    number = body.get('version')
    versions = DocumentVersion.objects.filter(project=project)
    if number is not None:
        version = versions.filter(number=number).first()
        if version is None:
            return Response({'detail': 'версия не найдена'},
                            status=status.HTTP_404_NOT_FOUND)
    else:
        # Последний снимок, а не текущее дерево: публикация должна быть
        # воспроизводимой, иначе «опубликовать версию 5» отдало бы 6.
        version = versions.order_by('-number').first()
        if version is None:
            return Response(
                {'detail': 'Сначала сохраните проект: нечего публиковать.'},
                status=status.HTTP_409_CONFLICT,
            )

    try:
        result = publish(project, version, slug=body.get('slug'))
    except PublishError as exc:
        record(
            project, ProjectEvent.KIND_PUBLISH, str(exc),
            status=ProjectEvent.STATUS_FAILED, actor=request.user,
        )
        return Response({'detail': str(exc)},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    audit(request, 'site.publish', project,
          f'{result.site.slug} v{result.version.number} {result.files} файлов')
    record(
        project, ProjectEvent.KIND_PUBLISH,
        f'Сайт опубликован: версия {result.version.number}, '
        f'{result.files} файлов. {result.url}',
        status=ProjectEvent.STATUS_OK, actor=request.user,
    )
    payload = status_payload(result.site)
    payload.update({
        'files': result.files,
        'size': result.size,
        'warnings': result.warnings,
    })
    return Response(payload, status=status.HTTP_201_CREATED)


def _parse_when(value) -> datetime | None:
    """Разбирает время публикации из ISO-строки.

    Наивное время считается местным: интерфейс присылает UTC, но
    ручной запрос через curl может прийти без зоны, и отказывать ему
    только из-за этого незачем.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = parse_datetime(value.strip())
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


@api_view(['GET', 'POST'])
@permission_classes([ProjectAccess])
def site_schedule(request, project_id: str):
    """Отложенная публикация: список и постановка задания.

    Версия собирается в момент постановки. Поэтому ошибка сборки видна
    сразу и не превращается в «сайт не обновился в нужный момент».
    """

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    site = Site.objects.filter(project=project).first()

    if request.method == 'GET':
        if site is None:
            return Response({'scheduled': []})
        return Response({'scheduled': [
            item.public_dict()
            for item in site.scheduled.filter(state=SCHEDULE_PENDING)
        ]})

    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Планировать публикацию может тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    when = _parse_when(body.get('at'))
    if when is None:
        return Response(
            {'detail': 'Укажите дату и время публикации в формате ISO 8601.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if when <= timezone.now():
        return Response(
            {'detail': 'Время публикации должно быть в будущем.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    number = body.get('version')
    versions = DocumentVersion.objects.filter(project=project)
    if number is not None:
        version = versions.filter(number=number).first()
        if version is None:
            return Response({'detail': 'версия не найдена'},
                            status=status.HTTP_404_NOT_FOUND)
    else:
        version = versions.order_by('-number').first()
        if version is None:
            return Response(
                {'detail': 'Сначала сохраните проект: нечего публиковать.'},
                status=status.HTTP_409_CONFLICT,
            )

    try:
        schedule, warnings = schedule_publication(
            project, version, when,
            user=request.user, slug=body.get('slug'),
        )
    except PublishError as exc:
        record(
            project, ProjectEvent.KIND_SCHEDULE, str(exc),
            status=ProjectEvent.STATUS_FAILED, actor=request.user,
        )
        return Response({'detail': str(exc)},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    moment = timezone.localtime(schedule.scheduled_at)
    audit(
        request, 'site.schedule', project,
        f'v{schedule.version_number} на {moment:%d.%m.%Y %H:%M}',
    )
    record(
        project, ProjectEvent.KIND_SCHEDULE,
        f'Публикация версии {schedule.version_number} запланирована на '
        f'{moment:%d.%m.%Y %H:%M}.',
        status=ProjectEvent.STATUS_INFO, actor=request.user,
    )
    payload = status_payload(schedule.site)
    payload.update({
        'schedule': schedule.public_dict(),
        'warnings': warnings,
    })
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([ProjectAccess])
def site_schedule_cancel(request, project_id: str, schedule_id: str):
    """Отменяет ожидающую публикацию. Выполненную отменить нельзя."""
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Отменять публикацию может тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        schedule_uuid = uuid.UUID(schedule_id)
    except (ValueError, AttributeError, TypeError):
        return Response({'detail': 'задание не найдено'},
                        status=status.HTTP_404_NOT_FOUND)

    schedule = (
        ScheduledPublication.objects
        .filter(
            pk=schedule_uuid, site__project=project,
            state=SCHEDULE_PENDING,
        )
        .select_related('site')
        .first()
    )
    if schedule is None:
        return Response({'detail': 'задание не найдено или уже выполнено'},
                        status=status.HTTP_404_NOT_FOUND)

    cancel_schedule(schedule)
    audit(request, 'site.schedule.cancel', project,
          f'v{schedule.version_number}')
    record(
        project, ProjectEvent.KIND_SCHEDULE,
        f'Отложенная публикация версии {schedule.version_number} отменена.',
        status=ProjectEvent.STATUS_INFO, actor=request.user,
    )
    return Response(status_payload(schedule.site))


@api_view(['POST'])
@permission_classes([ProjectAccess])
def project_site_withdraw(request, project_id: str):
    """Отзывает публикацию: сайт перестаёт открываться."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Отзывать публикацию может тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    site = Site.objects.filter(project=project).first()
    if site is None:
        return Response({'detail': 'сайт не опубликован'},
                        status=status.HTTP_409_CONFLICT)

    withdraw(site, remove_files=bool((request.data or {}).get('removeFiles')))
    audit(request, 'site.withdraw', project, site.slug)
    record(
        project, ProjectEvent.KIND_WITHDRAW,
        f'Публикация отозвана: {site.slug}.',
        status=ProjectEvent.STATUS_INFO, actor=request.user,
    )
    return Response(status_payload(site))


@api_view(['POST'])
@permission_classes([ProjectAccess])
def project_site_backup(request, project_id: str):
    """Резервная копия текущей публикации (ТЗ п.16.3)."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Копии делает тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    site = Site.objects.filter(project=project).first()
    if site is None:
        return Response({'detail': 'сайт не опубликован'},
                        status=status.HTTP_409_CONFLICT)

    backup = backup_site(site)
    if backup is None:
        return Response({'detail': 'у сайта нет опубликованной версии'},
                        status=status.HTTP_409_CONFLICT)

    audit(request, 'site.backup', project, f'v{backup.number}')
    record(
        project, ProjectEvent.KIND_BACKUP,
        f'Резервная копия версии {backup.number} сделана.',
        status=ProjectEvent.STATUS_OK, actor=request.user,
    )
    return Response({'number': backup.number, 'size': backup.size,
                     'createdAt': backup.created_at.isoformat()})


@api_view(['GET'])
@permission_classes([ProjectAccess])
def site_backups(request, project_id: str):
    """Список резервных копий: из них можно восстановиться.

    Без списка копии существовали бы, но найти их было бы нечем.
    """
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    site = Site.objects.filter(project=project).first()
    if site is None:
        return Response({'backups': []})
    return Response({'backups': [
        {
            'id': str(backup.id),
            'version': backup.number,
            'size': backup.size,
            'createdAt': backup.created_at.isoformat(),
            # Доступно ли восстановление: копия может быть удалена с
            # диска, и тогда кнопка обещала бы пустое действие.
            'restorable': (backup.directory / 'index.html').is_file(),
        }
        for backup in site.backups.all()
    ]})


@api_view(['POST'])
@permission_classes([ProjectAccess])
def backup_restore(request, project_id: str, backup_id: str):
    """Восстанавливает публикацию из резервной копии (ТЗ п.16.3).

    Право — как у публикации: восстановление меняет то, что увидит
    посетитель, и сделать его должен тот, кто публикует.
    """
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Восстанавливать копию может тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    site = Site.objects.filter(project=project).first()
    backup = Backup.objects.filter(id=backup_id, site=site).first() if site else None
    if backup is None:
        return Response({'detail': 'копия не найдена'},
                        status=status.HTTP_404_NOT_FOUND)

    try:
        version = restore_backup(site, backup)
    except PublishError as exc:
        record(
            project, ProjectEvent.KIND_RESTORE, str(exc),
            status=ProjectEvent.STATUS_FAILED, actor=request.user,
        )
        return Response({'detail': str(exc)},
                        status=status.HTTP_409_CONFLICT)

    audit(request, 'site.restore', project, f'v{version.number}')
    record(
        project, ProjectEvent.KIND_RESTORE,
        f'Сайт возвращён к копии версии {version.number}.',
        status=ProjectEvent.STATUS_OK, actor=request.user,
    )
    return Response(status_payload(site))