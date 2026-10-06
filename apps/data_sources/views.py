"""Представления узлов данных.

Права те же, что и у проекта (роль из ТЗ п.11.1): править записи может
тот, кому разрешено править контент, а удалить источник — владелец.

Зачем проверять права здесь, а не декоратором: у проекта проверка
делается в самой функции (permission_classes не знает проект), и
источник — то же самое. Единый набор правил важнее красивой
декоративной обёртки.
"""

from __future__ import annotations

import uuid

from django.db.models import Count
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import EDIT_CONTENT, VIEW, can
from accounts.permissions import IsAuthenticatedUser
from accounts.serializers import audit
from projects.models import Project

from .models import MAX_RECORDS, DataRecord, DataSource
from .serializers import DataRecordSerializer, DataSourceSerializer


def _project(project_id: str):
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).select_related('owner').first()
    except (ValueError, AttributeError, TypeError):
        return None


def _source(source_id: str):
    try:
        return (
            DataSource.objects.filter(pk=uuid.UUID(source_id))
            .select_related('project')
            .first()
        )
    except (ValueError, AttributeError, TypeError):
        return None


def _forbidden():
    return Response({'detail': 'Недостаточно прав.'}, status=status.HTTP_403_FORBIDDEN)


def _not_found():
    # 404, а не 403: иначе по коду ответа перебором выявляются
    # существующие проекты и источники.
    return Response({'detail': 'не найдено'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def source_list(request, project_id: str):
    """Источники данных проекта: список и создание."""

    project = _project(project_id)
    if project is None:
        return _not_found()
    # Нет доступа на чтение — 404, а не 403: иначе по коду ответа
    # перебором выявляются существующие проекты. Право на правку при
    # этом есть (Viewer читает узлы данных, но не меняет их).
    if not can(request.user, project, VIEW):
        return _not_found()
    if request.method != 'GET' and not can(request.user, project, EDIT_CONTENT):
        return _forbidden()

    if request.method == 'GET':
        sources = (
            DataSource.objects.filter(project=project)
            .annotate(record_count=Count('records'))
            .order_by('created_at')
        )
        return Response(DataSourceSerializer(sources, many=True).data)

    serializer = DataSourceSerializer(
        data=request.data,
        context={'project': project, 'request': request},
    )
    serializer.is_valid(raise_exception=True)
    source = serializer.save(project=project)
    audit(request, 'data.create', project, str(source.id))
    return Response(
        DataSourceSerializer(source).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def source_detail(request, source_id: str):
    """Один источник данных."""

    source = _source(source_id)
    if source is None:
        return _not_found()
    if not can(request.user, source.project, VIEW):
        return _not_found()
    if request.method != 'GET' and not can(request.user, source.project, EDIT_CONTENT):
        return _forbidden()

    if request.method == 'GET':
        return Response(DataSourceSerializer(source).data)

    if request.method == 'DELETE':
        audit(request, 'data.delete', source.project, str(source.id))
        source.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = DataSourceSerializer(
        source,
        data=request.data,
        partial=request.method == 'PATCH',
        context={'project': source.project, 'request': request},
    )
    serializer.is_valid(raise_exception=True)
    saved = serializer.save()
    # Смена полей может оставить записи с неизвестными ключами. Данные
    # не трогаем: удалять значения молча нельзя, а ломать запись тоже.
    # Пропущенное попадёт в лог обмена на этапе 1С (ТЗ п.7.5.3).
    audit(request, 'data.update', source.project, str(source.id))
    return Response(DataSourceSerializer(saved).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def record_list(request, source_id: str):
    """Записи источника."""

    source = _source(source_id)
    if source is None:
        return _not_found()
    if not can(request.user, source.project, VIEW):
        return _not_found()
    if request.method != 'GET' and not can(request.user, source.project, EDIT_CONTENT):
        return _forbidden()

    if request.method == 'GET':
        # Постраничность осознанно простая: показывается срез с лимитом,
        # полный экспорт и поиск по узлу появятся вместе с визуальной CMS.
        try:
            limit = int(request.query_params.get('limit', 100))
        except (TypeError, ValueError):
            return Response(
                {'detail': 'limit должен быть числом'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, MAX_RECORDS))
        records = source.records.all()[:limit]
        return Response(
            {
                'total': source.records.count(),
                'records': DataRecordSerializer(records, many=True).data,
            }
        )

    if source.records.count() >= MAX_RECORDS:
        return Response(
            {'detail': f'В источнике уже {MAX_RECORDS} записей.'},
            status=status.HTTP_409_CONFLICT,
        )

    serializer = DataRecordSerializer(
        data=request.data,
        context={'source': source, 'request': request},
    )
    serializer.is_valid(raise_exception=True)
    record = serializer.save()
    return Response(
        DataRecordSerializer(record).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def record_detail(request, record_id: str):
    """Одна запись."""

    record = DataRecord.objects.filter(pk=record_id).select_related('source').first()
    if record is None:
        return _not_found()
    if not can(request.user, record.source.project, VIEW):
        return _not_found()
    if request.method != 'GET' and not can(request.user, record.source.project, EDIT_CONTENT):
        return _forbidden()

    if request.method == 'GET':
        return Response(DataRecordSerializer(record).data)

    if request.method == 'DELETE':
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = DataRecordSerializer(
        record,
        data=request.data,
        partial=True,
        context={'source': record.source, 'request': request},
    )
    serializer.is_valid(raise_exception=True)
    saved = serializer.save()
    return Response(DataRecordSerializer(saved).data)
