"""Вход посетителя Mini App.

Посетитель открывает приложение из Telegram, поэтому он не
зарегистрирован в платформе. Полноценная учётная запись ему не нужна
и была бы неуместна: он не пользователь платформы.

Платформе от него нужно знать одно: пришедший действительно открыл
Mini App этого бота и он тот же, кто открыл минуту назад. Это подпись,
а не сессия. Токен называется edge-токеном (ТЗ п.92: «публичные
сайты используют отдельный механизм (Edge-токен) для изменяемых
запросов»), живёт недолго и привязан к боту и проекту.

Формат собственный: `payload.signature`, где payload — base64url от
JSON, а подпись — HMAC-SHA256 от него. Своя реализация вместо JWT
здесь и в том, что edge-токен не должен быть похож на токен
пользователя платформы: смешивать два разных по смыслу токена в одном
формате — значит потом не отличить их в логах и разборах.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

#: Сколько живёт edge-токен. Открытие Mini App — это один заход
#: посмотреть, а не работа с документами: час делал бы токен почти
#: постоянным и оставлял бы украденный пригодным надолго.
EDGE_TOKEN_TTL = 60 * 60


class EdgeTokenInvalid(ValueError):
    """Edge-токон не прошёл проверку."""


@dataclass(frozen=True)
class EdgeToken:
    """Что подтверждает edge-токен."""

    telegram_user_id: int
    bot: str
    project: str
    expires_at: int


def _key() -> bytes:
    """Ключ подписи edge-токенов."""
    from django.conf import settings

    return str(settings.SECRET_KEY).encode('utf-8')


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _unb64(value: str) -> bytes:
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_edge_token(*, telegram_user_id: int, bot_username: str,
                     project_id: str, now: int | None = None) -> str:
    """Выпускает edge-токен для посетителя Mini App."""
    issued = now if now is not None else int(time.time())
    payload = {
        't': int(telegram_user_id),
        'b': bot_username,
        'p': str(project_id),
        # Срок в секундах, а не абсолютное время: токен нельзя
        # «продлить», не выпустив новый, и в проверке не нужен доступ
        # к часам сервера, отличным от тех, что выдали токен.
        'x': issued + EDGE_TOKEN_TTL,
    }
    body = _b64(json.dumps(payload, separators=(',', ':'),
                          sort_keys=True).encode('utf-8'))
    signature = _b64(hmac.new(_key(), body.encode('ascii'),
                              hashlib.sha256).digest())
    return f'{body}.{signature}'


def read_edge_token(raw: str, *, now: int | None = None) -> EdgeToken:
    """Проверяет edge-токен и возвращает его утверждения."""
    if not raw or raw.count('.') != 1:
        raise EdgeTokenInvalid('токен повреждён')
    body, signature = raw.split('.')
    wanted = _b64(hmac.new(_key(), body.encode('ascii'),
                           hashlib.sha256).digest())
    if not hmac.compare_digest(wanted, signature):
        raise EdgeTokenInvalid('подпись не совпадает')
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError) as e:
        raise EdgeTokenInvalid('тело токена не разобрано') from e
    if not isinstance(payload, dict) or 't' not in payload or 'x' not in payload:
        raise EdgeTokenInvalid('в токене нет нужных полей')
    current = now if now is not None else int(time.time())
    if int(payload['x']) <= current:
        raise EdgeTokenInvalid('токен истёк')
    return EdgeToken(
        telegram_user_id=int(payload['t']),
        bot=str(payload.get('b', '')),
        project=str(payload.get('p', '')),
        expires_at=int(payload['x']),
    )


__all__ = [
    'EDGE_TOKEN_TTL',
    'EdgeToken',
    'EdgeTokenInvalid',
    'issue_edge_token',
    'read_edge_token',
]