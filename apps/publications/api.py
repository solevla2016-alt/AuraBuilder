"""API публикации: опубликовать, посмотреть состояние, отозвать.

Право — PUBLISH: публикация делает сайт доступным по адресу, и это
действие тарифов (ТЗ п.17.1), а не чтение проекта. Состояние
публикации видно всем, кто читает проект: «сайт опубликован, но не
работает» должно быть видно раньше, чем об этом узнает посетитель.
"""

from __future__ import annotations

import uuid

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import PUBLISH, VIEW, ProjectAccess, can
from accounts.serializers import audit
from projects.models import DocumentVersion, Project

from .models import Backup, Site
from .service import (
    PublishError,
    backup_site,
    publish,
    restore_backup,
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
        return Response({'detail': str(exc)},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    audit(request, 'site.publish', project,
          f'{result.site.slug} v{result.version.number} {result.files} файлов')
    payload = status_payload(result.site)
    payload.update({
        'files': result.files,
        'size': result.size,
        'warnings': result.warnings,
    })
    return Response(payload, status=status.HTTP_201_CREATED)


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
        return Response({'detail': str(exc)},
                        status=status.HTTP_409_CONFLICT)

    audit(request, 'site.restore', project, f'v{version.number}')
    return Response(status_payload(site))