"""Доставка событий проекта на адреса вебхуков.

Доставка best-effort, как и уведомления в Telegram: публикация уже
произошла, когда событие уходит наружу, и недоступный адрес не должен
менять её результат. Но, в отличие от Telegram, здесь остаётся запись о
неудаче: интеграция — часть рабочего процесса, и «почему мой сервис
ничего не получил» должно иметь ответ в интерфейсе.

Подпись считается по точным байтам тела. Получатель проверяет её тем же
секретом и убеждается, что запрос пришёл от нас и тело не подменили по
дороге. Идентификатор доставки в заголовке позволяет отбросить повтор:
сеть могла оборвать ответ уже после того, как сервис всё обработал.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request

from django.utils import timezone

from .models import (
    MAX_ATTEMPTS,
    MAX_DELIVERIES,
    SIGNATURE_HEADER,
    WebhookDelivery,
)

logger = logging.getLogger(__name__)

#: Таймаут одной попытки. Короткий намеренно: доставка идёт внутри
#: сохранения события, и «полминуты на каждый адрес» заметил бы человек,
#: который просто нажал «Опубликовать».
TIMEOUT = 3


def sign(secret: str, body: bytes) -> str:
    """Подпись тела в формате «sha256=<hex>».

    Префикс алгоритма оставлен, чтобы получатель мог добавить другой
    алгоритм, не ломая старых приёмников.
    """

    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256)
    return f'sha256={digest.hexdigest()}'


def payload_body(payload: dict) -> bytes:
    """Тело запроса. Разделители без пробелов — чтобы подпись совпадала
    у нас и у получателя независимо от настроек json на его стороне."""

    return json.dumps(
        payload, ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')


def build_payload(event, delivery: WebhookDelivery) -> dict:
    """Сообщение о событии, самодостаточное для получателя.

    Название проекта дублируется: получатель не обязан знать наши
    идентификаторы, а в журнале проекта имя уже могло измениться.
    """

    return {
        'delivery': str(delivery.id),
        'webhook': str(delivery.webhook_id),
        'project': {
            'id': str(event.project_id),
            'name': event.project.name,
        },
        'event': {
            'id': str(event.id),
            'kind': event.kind,
            'status': event.status,
            'message': event.message,
            'actor': event.actor.username if event.actor else None,
            'createdAt': event.created_at.isoformat(),
        },
        'sentAt': timezone.now().isoformat(),
    }


def _post(url: str, body: bytes, headers: dict) -> tuple[int | None, str]:
    """Одна попытка POST. Возвращает код ответа и текст ошибки.

    Разделено с send() ради тестов: проверять подпись и разбор ответа
    можно, не поднимая настоящий HTTP-сервер.
    """

    request = urllib.request.Request(url, data=body, headers=headers,
                                     method='POST')
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, ''
    except urllib.error.HTTPError as e:
        # HTTPError — это тоже ответ: сервис жив, но отказался принять.
        return e.code, f'HTTP {e.code}: {e.reason}'[:300]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, 'reason', e)
        return None, f'нет связи: {reason}'[:300]


def send(delivery: WebhookDelivery) -> bool:
    """Отправляет одну доставку и записывает результат. True — приняли."""

    webhook = delivery.webhook
    body = payload_body(delivery.payload)
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'AuraBuilder-Webhooks/1',
        'X-Aura-Event': delivery.event_kind,
        'X-Aura-Delivery': str(delivery.id),
        SIGNATURE_HEADER: sign(webhook.secret, body),
    }

    code, error = _post(webhook.url, body, headers)
    ok = code is not None and 200 <= code < 300

    delivery.attempts += 1
    delivery.response_code = code
    delivery.status = (
        WebhookDelivery.STATUS_OK if ok else WebhookDelivery.STATUS_FAILED
    )
    delivery.error = error
    delivery.delivered_at = timezone.now() if ok else None
    delivery.save(update_fields=[
        'attempts', 'response_code', 'status', 'error', 'delivered_at',
    ])
    return ok


def dispatch(event) -> list[WebhookDelivery]:
    """Создаёт доставки для подходящих вебхуков и сразу пытается их отправить.

    Сначала создаются все записи, потом идут запросы. Иначе медленный
    первый адрес задерживал бы создание записи для второго, и при падении
    процесса в журнале не осталось бы даже следа о неначатой доставке.
    """

    deliveries: list[WebhookDelivery] = []
    hooks = event.project.webhooks.filter(active=True)
    for hook in hooks:
        if not hook.subscribes_to(event.kind):
            continue
        try:
            delivery = WebhookDelivery(
                webhook=hook,
                event_kind=event.kind,
                event_id=str(event.id),
                payload={},
            )
            # Идентификатор уже известен до сохранения: UUID-поле получает
            # значение при создании объекта, поэтому id попадает в payload
            # тем же, что увидит получатель в заголовке.
            delivery.payload = build_payload(event, delivery)
            delivery.save()
            _prune(hook)
            deliveries.append(delivery)
        except Exception:  # noqa: BLE001 — один адрес не отменяет остальные
            logger.exception('не удалось создать доставку вебхука %s', hook.pk)

    for delivery in deliveries:
        try:
            send(delivery)
        except Exception:  # noqa: BLE001 — доставка не входит в операцию
            logger.exception('доставка %s не выполнена', delivery.pk)
    return deliveries


def _prune(webhook) -> None:
    stale = list(
        webhook.deliveries.order_by('-created_at')
        .values_list('id', flat=True)[MAX_DELIVERIES:]
    )
    if stale:
        webhook.deliveries.filter(id__in=stale).delete()


def retry_failed(limit: int = 50) -> tuple[int, int]:
    """Повторяет неудачные доставки в пределах MAX_ATTEMPTS.

    Вызывается командой для cron. Выключенный вебхук не повторяем: его
    остановили намеренно, и трафик по нему был бы сюрпризом.
    """

    query = (
        WebhookDelivery.objects
        .filter(status=WebhookDelivery.STATUS_FAILED,
                attempts__lt=MAX_ATTEMPTS,
                webhook__active=True)
        .select_related('webhook')
        .order_by('created_at')[:limit]
    )
    sent = failed = 0
    for delivery in query:
        try:
            if send(delivery):
                sent += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001 — одна доставка не срывает прогон
            logger.exception('повтор доставки %s не выполнен', delivery.pk)
            failed += 1
    return sent, failed


__all__ = [
    'TIMEOUT',
    'dispatch',
    'payload_body',
    'retry_failed',
    'send',
    'sign',
]
