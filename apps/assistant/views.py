"""API ИИ-помощника под проектом.

Чтение состояния доступно всем участникам, включая Viewer: знать,
сколько кредитов осталось и что умеет помощник, полезно и тому, кто
только смотрит. Запуск требует права на содержимое — иначе наблюдатель
тратил бы кредиты владельца.

Кредиты списываются с владельца проекта; в журнале остаётся, кто
нажал кнопку. Так общий проект не превращается в способ бесплатно
пользоваться чужим тарифом.
"""

from __future__ import annotations

import uuid

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import EDIT_CONTENT, VIEW, IsAuthenticatedUser, can
from projects.models import Project

from . import credits
from .service import (
    InputError,
    ProviderError,
    run,
    status as build_status,
)


def _access(request, project_id: str):
    """Проект и проверка чтения.

    Отдельный ответ для неизвестного проекта и для чужого: 404 в обоих
    случаях, чтобы по коду нельзя было перебрать идентификаторы.
    """
    try:
        project_pk = uuid.UUID(project_id)
    except (ValueError, AttributeError, TypeError):
        project_pk = None
    project = (
        Project.objects.select_related('owner').filter(pk=project_pk).first()
        if project_pk is not None else None
    )
    if project is None or not can(request.user, project, VIEW):
        return None, Response(
            {'detail': 'проект не найден'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return project, None


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def assistant_status(request, project_id: str):
    """Кредиты, действия и последние запросы по проекту."""
    project, error = _access(request, project_id)
    if error is not None:
        return error
    return Response(build_status(project, request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def assistant_run(request, project_id: str):
    """Выполняет действие помощника и списывает кредиты."""
    project, error = _access(request, project_id)
    if error is not None:
        return error

    if not can(request.user, project, EDIT_CONTENT):
        return Response(
            {'detail': 'Запускать помощника может тот, кто меняет '
                       'содержимое проекта.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    try:
        payload = run(
            project,
            request.user,
            str(body.get('action') or ''),
            body.get('description'),
        )
    except InputError as exc:
        return Response(
            {'detail': str(exc), 'reason': 'invalid_input'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except credits.InsufficientCredits as exc:
        return Response(
            {
                'detail': str(exc),
                'reason': 'credits_exhausted',
                'cost': exc.cost,
                'credits': credits.status_for(project.owner or request.user),
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )
    except ProviderError as exc:
        # 502, а не 500: сломалась внешняя модель, а не платформа.
        # Кредиты не списаны — провайдер вызван до списания.
        return Response(
            {'detail': str(exc), 'reason': 'provider_unavailable'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response(payload)


__all__ = ['assistant_run', 'assistant_status']
