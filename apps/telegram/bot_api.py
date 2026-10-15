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


def call(token: str, method: str, payload: dict | None = None) -> dict:
    """Вызывает метод Bot API и возвращает его результат."""
    body = json.dumps(payload or {}).encode('utf-8')
    request = urllib.request.Request(
        f'{API_ROOT}/bot{token}/{method}',
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
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


__all__ = [
    'API_ROOT',
    'BotApiError',
    'BotIdentity',
    'call',
    'delete_web_app_menu',
    'set_web_app_menu',
    'verify_token',
]