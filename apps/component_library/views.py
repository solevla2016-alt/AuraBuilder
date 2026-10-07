"""Представления библиотеки компонентов (ТЗ п.3.1).

Маршруты:

    /api/projects/<id>/component-styles/          — список стилей
    /api/projects/<id>/component-styles/<kind>/   — стиль вида

Стили отдаются всегда, включая умолчания: клиент рисует макет
компонента и должен знать фактические значения, а не угадывать их.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import EDIT_CONTENT, VIEW, can
from accounts.permissions import IsAuthenticatedUser
from accounts.serializers import audit
from projects.models import Project

from .models import COMPONENT_KINDS, ComponentStyle
from .serializers import ComponentStyleSerializer, style_payload

KIND_CODES = tuple(code for code, _ in COMPONENT_KINDS)


def _project(project_id: str):
    try:
        return (
            Project.objects.filter(pk=uuid.UUID(project_id)).select_related('owner').first()
        )
    except (ValueError, AttributeError, TypeError):
        return None


def _not_found():
    return Response({'detail': 'Не найдено.'}, status=status.HTTP_404_NOT_FOUND)


def _forbidden():
    return Response({'detail': 'Недостаточно прав.'}, status=status.HTTP_403_FORBIDDEN)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def style_list(request, project_id: str):
    """Стили всех видов компонентов проекта."""

    project = _project(project_id)
    # Отсутствующий и чужой проект отвечают одинаково: иначе по коду
    # ответа можно перебрать чужие проекты.
    if project is None or not can(request.user, project, VIEW):
        return _not_found()

    stored = {s.kind: s for s in ComponentStyle.objects.filter(project=project)}
    return Response({'styles': [style_payload(kind, stored.get(kind)) for kind in KIND_CODES]})


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def style_detail(request, project_id: str, kind: str):
    """Стиль одного вида компонента."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return _not_found()
    if kind not in KIND_CODES:
        return Response(
            {'detail': f'Неизвестный компонент «{kind}».'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not can(request.user, project, EDIT_CONTENT):
        return _forbidden()

    style = ComponentStyle.objects.filter(project=project, kind=kind).first()

    if request.method == 'DELETE':
        # Сброс к умолчанию удаляет строку, а не пишет значения по
        # умолчанию: тогда набор токенов в БД всегда означает
        # «пользователь это выбрал».
        if style is not None:
            style.delete()
            audit(request, 'components.reset', project, kind)
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = ComponentStyleSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    tokens = serializer.validated_data['tokens']

    # Гонка двух вкладок не должна давать 500: ограничение уникальности
    # срабатывает на второй записи, и запрос должен честно сказать
    # «занято», а не упасть.
    try:
        if style is None:
            style = ComponentStyle.objects.create(project=project, kind=kind, tokens=tokens)
        else:
            style.tokens = tokens
            style.save(update_fields=['tokens', 'updated_at'])
    except IntegrityError:
        return Response(
            {'kind': ['Стиль уже сохранён другим редактором. Обновите страницу.']},
            status=status.HTTP_409_CONFLICT,
        )

    audit(request, 'components.update', project, kind)
    return Response(style_payload(kind, style))