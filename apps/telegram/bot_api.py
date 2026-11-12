"""Разговор с Telegram Bot API.

Внешние вызовы собраны в одном месте по двум причинам: их нельзя
размазывать по представлениям, и их нельзя выполнять молча. Сеть
доступна не всегда, а «меню не настроилось, но пользователю сказали,
что настроилось» — худший вид молчания.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Bot API не меняет адрес десятилетиями; значение в коде — намеренно:
#: подменять его во время работы нечем.
API_ROOT = 'https://api.telegram.org'

#: Секунд на попытку и попыток. Один зависший запрос к Telegram не
#: должен держать HTTP-запрос платформы дольше терпения посетителя.
TIMEOUT = 8
ATTEMPTS = 2

#: Уведомления и разбор входящих — вспомогательные операции. Ждать их
#: столько же, сколько настройку меню, незачем: публикация не должна
#: зависеть от того, отвечает ли Telegram прямо сейчас.
UPDATE_TIMEOUT = 5
SEND_TIMEOUT = 5


class BotApiError(RuntimeError):
    """Telegram не принял запрос."""


@dataclass(frozen=True)
class BotIdentity:
    """Кто этот бот."""

    id: int
    username: str
    first_name: str = ''
    can_join_groups: bool | None = None

    @property
    def is_bot(self) -> bool:
        return True


def call(token: str, method: str, payload: dict | None = None,
         *, attempts: int = ATTEMPTS, timeout: int = TIMEOUT) -> dict:
    """Вызывает метод Bot API и возвращает его результат."""
    body = json.dumps(payload or {}).encode('utf-8')
    request = urllib.request.Request(
        f'{API_ROOT}/bot{token}/{method}',
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            # Telegram отвечает JSON даже на ошибку, и в нём есть
            # человекочитаемый description: «Bad Request: chat not found»
            # полезнее, чем код 400.
            detail = ''
            try:
                detail = json.loads(e.read().decode('utf-8')).get(
                    'description', '',
                )
            except Exception:
                detail = e.reason or ''
            raise BotApiError(
                f'Telegram отклонил {method}: {detail or e.code}',
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            logger.warning('Bot API %s недоступен (%s), попытка %s',
                           method, e, attempt + 1)
            continue
        if not data.get('ok'):
            raise BotApiError(
                f'Telegram отклонил {method}: {data.get("description", "")}',
            )
        return data.get('result') or {}
    raise BotApiError(f'Telegram недоступен: {last}')


def verify_token(token: str) -> BotIdentity:
    """Проверяет токен и узнаёт, чей это бот."""
    result = call(token, 'getMe')
    return BotIdentity(
        id=int(result.get('id', 0)),
        username=str(result.get('username', '')),
        first_name=str(result.get('first_name', '')),
    )


def set_web_app_menu(token: str, url: str, button_text: str = 'Открыть') -> dict:
    """Настраивает кнопку меню бота (ТЗ п.16.6).

    После этого любой, кто откроет бота, увидит кнопку входа в Mini App
    — это и есть «автоматическая настройка WebApp-меню».
    """
    return call(token, 'setChatMenuButton', {
        'menu_button': {
            'type': 'web_app',
            'text': button_text,
            'web_app': {'url': url},
        },
    })


def delete_web_app_menu(token: str) -> dict:
    """Убирает кнопку: бот больше не открывает Mini App."""
    return call(token, 'setChatMenuButton', {'menu_button': {'type': 'default'}})


def get_updates(token: str, limit: int = 20) -> list[dict]:
    """Последние сообщения бота.

    Нужны, чтобы привязать чат для уведомлений: человек пишет боту
    /start, платформа читает, от кого пришло сообщение, и запоминает
    chat_id. Webhook для этого не нужен — он требует публичного HTTPS и
    перестал бы работать в стенде, а getUpdates доступен всегда.

    Одна попытка и короткий timeout: разбор входящих — вспомогательная
    операция, и зависший Telegram не должен держать запрос.
    """
    result = call(
        token, 'getUpdates',
        {'limit': limit, 'timeout': 0, 'allowed_updates': ['message']},
        attempts=1,
        timeout=UPDATE_TIMEOUT,
    )
    return result if isinstance(result, list) else []


def latest_chat(updates: list[dict]) -> tuple[int, str] | None:
    """Чат последнего сообщения: (id, подпись) или None.

    Сначала ищем личный чат: уведомления проекта должны уходить
    владельцу, а не в случайную группу, где бота упомянули последним.
    """
    if not updates:
        return None

    def chat_of(update):
        message = update.get('message') or update.get('edited_message') or {}
        return message.get('chat') or {}

    for update in reversed(updates):
        chat = chat_of(update)
        if chat.get('type') == 'private' and chat.get('id') is not None:
            return int(chat['id']), _chat_title(chat)
    for update in reversed(updates):
        chat = chat_of(update)
        if chat.get('id') is not None:
            return int(chat['id']), _chat_title(chat)
    return None


def _chat_title(chat: dict) -> str:
    title = chat.get('title') or ''
    if not title:
        title = ' '.join(
            part for part in (chat.get('first_name'), chat.get('last_name'))
            if part
        )
    return title or str(chat.get('username') or chat.get('id') or '')


def send_message(token: str, chat_id: int, text: str) -> dict:
    """Отправляет сообщение в чат.

    Одна попытка: уведомление — не операция, ради которой стоит держать
    публикацию ещё восемь секунд. Не доставленное сообщение остаётся в
    журнале проекта, и его видно на экране публикации.
    """
    return call(
        token, 'sendMessage',
        {
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': True,
        },
        attempts=1,
        timeout=SEND_TIMEOUT,
    )


__all__ = [
    'API_ROOT',
    'BotApiError',
    'BotIdentity',
    'call',
    'delete_web_app_menu',
    'get_updates',
    'latest_chat',
    'send_message',
    'set_web_app_menu',
    'verify_token',
]