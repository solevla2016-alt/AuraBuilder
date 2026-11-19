"""API вебхуков и журнала доставок.

Все действия требуют MANAGE_INTEGRATIONS: адрес вебхука и его секрет —
это настройка интеграции, а не содержимое сайта. Viewer и редактор
контента не должны видеть секрет подписи: с ним можно подделать запрос
к чужому приёмнику.

Проект и вебхук проверяются вместе: вебхук ищется только среди вебхуков
этого проекта. Иначе участник одного проекта мог бы читать журнал
доставок другого, зная идентификатор.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import (
    MANAGE_INTEGRATIONS,
    VIEW,
    IsAuthenticatedUser,
    can,
)
from accounts.serializers import audit
from projects.models import Project, ProjectEvent

from .models import MAX_WEBHOOKS, Webhook, new_secret
from .service import send

EVENT_KINDS = {value for value, _label in ProjectEvent.KIND_CHOICES}
#: Сколько доставок показывать в списке и сколько в карточке. Список —
#: чтобы не открывать карточку ради последней ошибки; карточка — чтобы
#: разобрать вчерашний сбой, не выгружая весь журнал.
LIST_DELIVERIES = 5
DETAIL_DELIVERIES = 30


def _project(project_id: str) -> Project | None:
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, AttributeError, TypeError):
        return None


def _webhook(project: Project, webhook_id: str):
    """Вебхук проекта. Возвращает пару «вебхук или ответ с ошибкой»."""

    try:
        hook_uuid = uuid.UUID(webhook_id)
    except (ValueError, AttributeError, TypeError):
        hook_uuid = None
    hook = (
        project.webhooks.filter(pk=hook_uuid).first()
        if hook_uuid is not None else None
    )
    if hook is None:
        return None, Response(
            {'detail': 'вебхук не найден'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return hook, None


def _access(request, project_id: str):
    """Проект и проверка права на интеграции.

    Разные ответы для «нет проекта» и «нет права»: участник, который
    видит проект, но не управляет интеграциями, должен понять, что дело
    в роли, а не в удалённом проекте.
    """

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return None, Response(
            {'detail': 'проект не найден'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if not can(request.user, project, MANAGE_INTEGRATIONS):
        return None, Response(
            {'detail': 'Вебхуками управляет тот, кому доступны интеграции.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    return project, None


def _clean_url(raw) -> tuple[str | None, Response | None]:
    url = str(raw or '').strip()
    if not url:
        return None, Response(
            {'detail': 'Укажите адрес приёмника.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(url) > 500:
        return None, Response(
            {'detail': 'Адрес — не длиннее 500 символов.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    parsed = urlparse(url)
    # Только http(s): file:// и ftp:// означали бы, что «вебхук» читает
    # файлы или ходит по чужим протоколам от имени платформы.
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None, Response(
            {'detail': 'Адрес должен начинаться с http:// или https://.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return url, None


def _clean_events(raw) -> tuple[list[str] | None, Response | None]:
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, Response(
            {'detail': 'events: ожидается список видов событий.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    values: list[str] = []
    for item in raw:
        value = str(item)
        if value not in EVENT_KINDS:
            return None, Response(
                {'detail': f'Неизвестное событие: {value}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if value not in values:
            values.append(value)
    return values, None


def _hook_payload(hook: Webhook, limit: int = LIST_DELIVERIES) -> dict:
    deliveries = list(hook.deliveries.all()[:limit])
    latest = deliveries[0] if deliveries else None
    return hook.public_dict(latest=latest, deliveries=deliveries)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def webhook_list(request, project_id: str):
    """Подписки проекта и создание новой."""

    project, error = _access(request, project_id)
    if error is not None:
        return error

    if request.method == 'GET':
        hooks = project.webhooks.all()
        return Response({
            'webhooks': [_hook_payload(hook) for hook in hooks],
            'events': [
                {'id': value, 'label': label}
                for value, label in ProjectEvent.KIND_CHOICES
            ],
            'limit': MAX_WEBHOOKS,
        })

    body = request.data or {}
    url, error = _clean_url(body.get('url'))
    if error is not None:
        return error
    events, error = _clean_events(body.get('events'))
    if error is not None:
        return error

    if project.webhooks.count() >= MAX_WEBHOOKS:
        return Response(
            {'detail': f'Достигнут предел вебхуков ({MAX_WEBHOOKS}): '
                       'удалите ненужные или отключите их.'},
            status=status.HTTP_409_CONFLICT,
        )

    hook = Webhook.objects.create(
        project=project,
        url=url,
        events=events,
        created_by=request.user,
    )
    audit(request, 'webhook.create', project, url)
    return Response(_hook_payload(hook), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def webhook_detail(request, project_id: str, webhook_id: str):
    """Карточка вебхука: журнал доставок, правка и удаление."""

    project, error = _access(request, project_id)
    if error is not None:
        return error

    hook, error = _webhook(project, webhook_id)
    if error is not None:
        return error

    if request.method == 'GET':
        return Response(_hook_payload(hook, DETAIL_DELIVERIES))

    if request.method == 'DELETE':
        url = hook.url
        hook.delete()
        audit(request, 'webhook.delete', project, url)
        return Response(status=status.HTTP_204_NO_CONTENT)

    body = request.data or {}
    if 'url' in body:
        url, error = _clean_url(body.get('url'))
        if error is not None:
            return error
        hook.url = url
    if 'events' in body:
        events, error = _clean_events(body.get('events'))
        if error is not None:
            return error
        hook.events = events
    if 'active' in body:
        hook.active = bool(body.get('active'))

    hook.save(update_fields=['url', 'events', 'active'])
    audit(request, 'webhook.update', project, hook.url)
    return Response(_hook_payload(hook))


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def webhook_rotate(request, project_id: str, webhook_id: str):
    """Выпускает новый секрет. Старый перестаёт приниматься сразу."""

    project, error = _access(request, project_id)
    if error is not None:
        return error

    hook, error = _webhook(project, webhook_id)
    if error is not None:
        return error

    hook.secret = new_secret()
    hook.save(update_fields=['secret'])
    audit(request, 'webhook.rotate', project, hook.url)
    return Response(_hook_payload(hook))


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def delivery_retry(request, project_id: str, webhook_id: str,
                   delivery_id: str):
    """Повторяет доставку вручную, без ограничения попыток.

    Автоматический повтор ограничен, а ручной — нет: человек видит
    ошибку и сам решает, что приёмник уже починили.
    """

    project, error = _access(request, project_id)
    if error is not None:
        return error

    hook, error = _webhook(project, webhook_id)
    if error is not None:
        return error

    try:
        delivery_uuid = uuid.UUID(delivery_id)
    except (ValueError, AttributeError, TypeError):
        delivery_uuid = None
    delivery = (
        hook.deliveries.filter(pk=delivery_uuid).first()
        if delivery_uuid is not None else None
    )
    if delivery is None:
        return Response(
            {'detail': 'доставка не найдена'},
            status=status.HTTP_404_NOT_FOUND,
        )

    send(delivery)
    audit(request, 'webhook.retry', project, hook.url)
    delivery.refresh_from_db()
    return Response(delivery.public_dict())
