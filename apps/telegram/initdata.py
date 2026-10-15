"""Проверка данных, которыми Telegram открывает Mini App.

Telegram передаёт приложению строку `initData` — набор параметров,
подписанных секретом бота. Доверия ей нет: строка приходит из
браузера посетителя, а не от Telegram.

Подпись проверяется так, как это описано в документации Telegram
Mini Apps:

* из параметров исключается `hash`, остальные сортируются по имени и
  склеиваются строками `имя=значение` через перевод строки;
* ключ подписи — SHA-256 от токена бота;
* HMAC-SHA256 ключа и этой строки должен совпасть с `hash`.

Проверяется не только подпись, но и срок: `initData` годен минуты, а
не дни, иначе перехваченная ссылка работала бы вечно.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

#: Сколько секунд назад `auth_date` ещё считается свежим.
#: Telegram не задаёт срок сам, и ссылка с initData может утечь через
#: историю браузера, прокси или скриншот; час — достаточный запас для
#: первого открытия и достаточно короткий для остального.
MAX_AUTH_AGE = 3600

#: Допуск по часам: телефоны посетителей спешат на минуты, а не на часы.
CLOCK_SKEW = 60


class InitDataInvalid(ValueError):
    """initData не прошла проверку."""


@dataclass(frozen=True)
class TelegramUser:
    """Пользователь Telegram по данным Mini App."""

    id: int
    username: str = ''
    first_name: str = ''
    last_name: str = ''
    language_code: str = ''
    is_premium: bool = False

    @property
    def display_name(self) -> str:
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'
        return self.first_name or (f'@{self.username}' if self.username
                                   else str(self.id))

    def as_dict(self) -> dict:
        return {
            'id': self.id,
            'username': self.username,
            'firstName': self.first_name,
            'lastName': self.last_name,
            'displayName': self.display_name,
            'languageCode': self.language_code,
            'isPremium': self.is_premium,
        }


def secret_key(bot_token: str) -> bytes:
    """Ключ подписи: SHA-256 от токена бота."""
    return hashlib.sha256(bot_token.encode('utf-8')).digest()


def parse_init_data(init_data: str) -> dict[str, str]:
    """Параметры initData как словарь.

    Значение user приходит JSON-строкой, поэтому оно сохраняется
    строкой и разбирается отдельно: иначе '&' внутри JSON разорвал бы
    параметр.
    """
    return dict(parse_qsl(init_data, keep_blank_values=True))


def data_check_string(params: dict[str, str]) -> str:
    """Строка, которую Telegram подписал."""
    return '\n'.join(
        f'{key}={params[key]}'
        for key in sorted(params)
        if key != 'hash'
    )


def expected_hash(bot_token: str, params: dict[str, str]) -> str:
    return hmac.new(
        secret_key(bot_token),
        data_check_string(params).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(init_data: str, bot_token: str) -> dict[str, str]:
    """Проверяет подпись и возвращает параметры.

    Сравнение — постоянного времени: побайтовое вернуло бы «правильный
    ответ на первый различающийся байт», что для подписи означает
    возможность подобрать её перебором.
    """
    params = parse_init_data(init_data)
    given = params.get('hash')
    if not given:
        raise InitDataInvalid('в initData нет подписи')
    if not bot_token:
        raise InitDataInvalid('токен бота не задан, подпись нечем проверить')
    wanted = expected_hash(bot_token, params)
    if not hmac.compare_digest(wanted, given):
        raise InitDataInvalid('подпись initData не совпадает')
    return params


def check_freshness(params: dict[str, str], *, now: float | None = None,
                    max_age: int = MAX_AUTH_AGE) -> None:
    """Проверяет, что данные свежие."""
    raw = params.get('auth_date')
    if not raw:
        raise InitDataInvalid('в initData нет auth_date')
    try:
        auth_date = int(raw)
    except ValueError as e:
        raise InitDataInvalid('auth_date не число') from e
    current = now if now is not None else time.time()
    age = current - auth_date
    if age > max_age + CLOCK_SKEW:
        raise InitDataInvalid('данные устарели, войдите заново')
    if age < -CLOCK_SKEW:
        # Часы спешат сильнее, чем на минуту: это подделка данных
        # времени, а не «пользователь поторопился».
        raise InitDataInvalid('время в initData из будущего')


def parse_user(raw: str) -> TelegramUser:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise InitDataInvalid('user в initData не разобран') from e
    if not isinstance(data, dict) or 'id' not in data:
        raise InitDataInvalid('в user нет идентификатора')
    try:
        user_id = int(data['id'])
    except (TypeError, ValueError) as e:
        raise InitDataInvalid('идентификатор пользователя не число') from e
    return TelegramUser(
        id=user_id,
        username=str(data.get('username') or ''),
        first_name=str(data.get('first_name') or ''),
        last_name=str(data.get('last_name') or ''),
        language_code=str(data.get('language_code') or ''),
        is_premium=bool(data.get('is_premium')),
    )


def verify(init_data: str, bot_token: str, *, now: float | None = None,
           max_age: int = MAX_AUTH_AGE) -> tuple[TelegramUser, dict[str, str]]:
    """Полная проверка: подпись, срок и пользователь.

    Возвращает пользователя и исходные параметры: параметры нужны
    вызывающему коду — по ним он понимает, откуда пришёл запуск.
    """
    if not init_data or not init_data.strip():
        raise InitDataInvalid('initData пуста')
    params = verify_signature(init_data, bot_token)
    check_freshness(params, now=now, max_age=max_age)
    user = parse_user(params.get('user', ''))
    return user, params


def sign(params: dict[str, str], bot_token: str) -> str:
    """Подписывает набор параметров токеном бота.

    Нужна не только для проверки: так проверяющие сценарии создают
    корректные данные без обращения к Telegram.
    """
    payload = {key: value for key, value in params.items() if key != 'hash'}
    payload['hash'] = expected_hash(bot_token, payload)
    from urllib.parse import urlencode
    return urlencode(payload)


__all__ = [
    'CLOCK_SKEW',
    'InitDataInvalid',
    'MAX_AUTH_AGE',
    'TelegramUser',
    'check_freshness',
    'data_check_string',
    'expected_hash',
    'parse_init_data',
    'parse_user',
    'secret_key',
    'sign',
    'verify',
    'verify_signature',
]