"""Сценарий 5 ТЗ п.16.7: выгрузка и импорт конфигурации проекта.

Права: экспорт доступен всем тарифам (ТЗ п.17.1) и любому, кто читает
проект, — это его собственный проект, а не выданный сайт. Импорт
создаёт новый проект у того, кто его загрузил.

Ограничение размера ответа и файла одинаковое с лимитом записей:
конфигурация растёт вместе с данными, и файл должен оставаться тем же
объектом, который можно отдать в архиве проекта.
"""

from __future__ import annotations

import json
import uuid

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from accounts.permissions import (
    VIEW,
    IsAuthenticatedUser,
    ProjectAccess,
    can,
)
from accounts.serializers import audit
from projects.config_export import (
    FORMAT_VERSION,
    ConfigError,
    import_project,
    to_json,
)
from projects.models import Project


def _project(project_id: str) -> Project | None:
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, TypeError):
        return None


@api_view(['GET'])
@permission_classes([ProjectAccess])
def project_config_export(request, project_id: str):
    """Отдаёт project.json со всей структурой проекта."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    payload = to_json(project)
    audit(request, 'project.config.export', project, str(len(payload)))

    response = HttpResponse(payload, content_type='application/json; charset=utf-8')
    # Имя файла ASCII: кириллица в Content-Disposition кодируется
    # браузерами по-разному, и часть клиентов показывает пользователю
    # «=?utf-8?b?...?=».
    name = ''.join(
        ch if ch.isascii() and (ch.isalnum() or ch in '-_') else '-'
        for ch in project.name
    ).strip('-') or 'project'
    response['Content-Disposition'] = content_disposition_header(
        as_attachment=True, filename=f'{name}-config.json'
    )
    response['X-AuraBuilder-Format-Version'] = str(FORMAT_VERSION)
    return response


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def project_config_import(request):
    """Создаёт проект из файла конфигурации.

    Вход не требует прав на проект: проекта ещё нет. Право есть у того,
    кто импортирует, — он и становится владельцем нового проекта.
    """

    body = request.data
    if not isinstance(body, dict) or (
        'project' not in body and 'format' not in body
    ):
        # Файл пришёл вложением или это просто мусор. Ответ 400 честнее
        # 422: файл не распознан как конфигурация вообще.
        return Response(
            {'detail': 'Пришлите содержимое project.json в теле запроса.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        project = import_project(request.user, body)
    except ConfigError as exc:
        return Response({'detail': str(exc)},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    audit(request, 'project.config.import', project, 'создан из файла')
    return Response(
        {
            'id': str(project.id),
            'name': project.name,
            'blocks': len(project.tree.get('blocks', [])),
            'versions': project.versions.count(),
        },
        status=status.HTTP_201_CREATED,
    )