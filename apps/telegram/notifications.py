"""Уведомления о событиях проекта в Telegram.

Доставка намеренно best-effort. Публикация и деплой уже завершены, когда
событие уходит в мессенджер, и недоступный Telegram не должен менять их
результат. Поэтому здесь нет очередей и повторов: сообщение либо ушло,
либо осталось в журнале проекта, где его видно на экране публикации.

Получатель — чат, который владелец привязал к боту. Без привязки
отправлять некуда, и это не ошибка: бот может использоваться только как
Mini App.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from secretstore.crypto import SecretsUnavailable

from .bot_api import BotApiError, send_message

logger = logging.getLogger(__name__)

STATUS_MARKS = {
    'ok': '✅',
    'failed': '⚠️',
    'info': 'ℹ️',
}


def format_event(event) -> str:
    """Текст сообщения: без HTML и markdown.

    Разметку Telegram пришлось бы экранировать, а имя проекта и текст
    ошибки приходят от пользователя. Простой текст всегда доходит и не
    ломается на символе «_» в адресе сайта.
    """

    mark = STATUS_MARKS.get(event.status, '•')
    lines = [
        f'{mark} {event.project.name}: {event.get_kind_display().lower()}',
        event.message,
    ]
    if event.actor is not None:
        lines.append(f'Автор: {event.actor.username}')
    lines.append(timezone.localtime(event.created_at).strftime('%d.%m.%Y %H:%M'))
    return '\n'.join(lines)


def notify_event(event) -> bool:
    """Отправляет событие в привязанный чат. True — сообщение ушло."""

    bot = (
        event.project.telegram_bots
        .filter(notify_chat_id__isnull=False)
        .exclude(token_encrypted='')
        .order_by('created_at')
        .first()
    )
    if bot is None:
        return False

    try:
        token = bot.get_token()
    except SecretsUnavailable:
        # Ключ шифрования пропал: токен не прочитать. Это уже видно в
        # настройках бота, а публикацию ронять из-за уведомления нельзя.
        logger.warning('уведомление не отправлено: токен бота @%s недоступен',
                       bot.bot_username)
        return False
    if not token:
        return False

    try:
        send_message(token, bot.notify_chat_id, format_event(event))
    except BotApiError as e:
        # Человек написал боту, а потом заблокировал его — Telegram
        # ответит «bot was blocked by the user». Событие остаётся в
        # журнале, привязку не сбрасываем: владелец мог разблокировать.
        logger.warning('уведомление @%s не доставлено: %s',
                       bot.bot_username, e)
        return False
    return True


__all__ = ['format_event', 'notify_event']
