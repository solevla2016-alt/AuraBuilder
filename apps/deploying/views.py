"""Профили хостинга и деплой: API сценария 3 (ТЗ п.16.5).

Что здесь и почему так: профиль описывает доступ к серверу заказчика,
деплой кладёт на него собранный пакет. Секрет профиля наружу не
отдаётся никогда — ни при создании, ни при чтении.

Роль та же, что у выгрузки: деплоить может тот, кто публикует
(п.17.1, п.16.4). Профиль читать и менять может любой участник
проекта, добавлять и удалять — владелец: чужой сервер не должен
достаться участнику, который уйдёт из проекта.
"""

from __future__ import annotations

import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import PUBLISH, VIEW, ProjectAccess, can
from accounts.serializers import audit
from projects.models import DocumentVersion, Project

from deploying.models import HostingProfile
from deploying.service import DeployError, deploy


def _project(project_id: str) -> Project | None:
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, TypeError):
        return None


def _can_manage(request, project: Project) -> bool:
    """Управлять доступом к серверу может владелец проекта."""
    return project.owner_id == request.user.id or request.user.is_superuser


@api_view(['GET', 'POST'])
@permission_classes([ProjectAccess])
def hosting_profiles(request, project_id: str):
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        profiles = HostingProfile.objects.filter(owner=project.owner).order_by('name')
        return Response([profile.public_dict() for profile in profiles])

    if not _can_manage(request, project):
        return Response(
            {'detail': 'Добавлять доступ к серверу может владелец проекта.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    name = str(body.get('name') or '').strip()
    if not name:
        return Response({'detail': 'Укажите название профиля.'},
                        status=status.HTTP_400_BAD_REQUEST)

    kind = str(body.get('kind') or 'ftp')
    if kind not in ('fs', 'ftp'):
        return Response({'detail': 'Неизвестный способ доступа.'},
                        status=status.HTTP_400_BAD_REQUEST)

    secret = str(body.get('secret') or '')
    if kind == 'ftp' and not secret:
        return Response(
            {'detail': 'Для FTP нужен пароль или ключ.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    profile = HostingProfile.objects.create(
        owner=project.owner,
        name=name,
        kind=kind,
        host=str(body.get('host') or ''),
        port=int(body.get('port') or 21),
        username=str(body.get('username') or ''),
        secret=secret,
        root_path=str(body.get('rootPath') or ''),
        runtime_path=str(body.get('runtimePath') or ''),
        site_url=str(body.get('siteUrl') or ''),
    )
    audit(request, 'hosting.profile.create', project, str(profile.id))
    return Response(profile.public_dict(), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([ProjectAccess])
def hosting_profile_detail(request, project_id: str, profile_id: str):
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    profile = HostingProfile.objects.filter(id=profile_id, owner=project.owner).first()
    if profile is None:
        return Response({'detail': 'профиль не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    if not _can_manage(request, project):
        return Response(
            {'detail': 'Менять доступ к серверу может владелец проекта.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'DELETE':
        audit(request, 'hosting.profile.delete', project, str(profile.id))
        profile.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    body = request.data or {}
    for field, key in (
        ('name', 'name'),
        ('host', 'host'),
        ('username', 'username'),
        ('root_path', 'rootPath'),
        ('runtime_path', 'runtimePath'),
        ('site_url', 'siteUrl'),
    ):
        if key in body:
            setattr(profile, field, str(body[key]))
    if 'port' in body:
        profile.port = int(body['port'] or 21)
    if body.get('secret'):
        # Пустой секрет означает «оставить прежний»: иначе правка
        # названия обнулила бы пароль и следующий деплой упал бы.
        profile.secret = str(body['secret'])
    profile.save()

    return Response(profile.public_dict())


@api_view(['POST'])
@permission_classes([ProjectAccess])
def project_deploy(request, project_id: str):
    """Выкладывает проект на хостинг по профилю.

    Право — как у выгрузки: деплой публикует сайт извне, и тарифы
    ограничивают его отдельно (п.17.1).
    """

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Публиковать проект может тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    profile = HostingProfile.objects.filter(
        id=str(body.get('profileId') or ''), owner=project.owner
    ).first()
    if profile is None:
        return Response({'detail': 'профиль хостинга не найден'},
                        status=status.HTTP_404_NOT_FOUND)

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
                {'detail': 'Сначала сохраните проект: нечего выкладывать.'},
                status=status.HTTP_409_CONFLICT,
            )

    started = timezone.now()
    try:
        result = deploy(
            project,
            version,
            profile,
            verify=body.get('verify', True) is not False,
            rotate_key=bool(body.get('rotateKey')),
        )
    except DeployError as exc:
        return Response({'detail': str(exc)},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    audit(request, 'project.deploy', project,
          f'{profile.id} v{version.number} {result.files_uploaded} файлов')

    payload = result.as_dict()
    payload['durationSeconds'] = round(
        (timezone.now() - started).total_seconds(), 1
    )
    return Response(payload)
