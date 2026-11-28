"""Где живёт общий кэш платформы.

Django по умолчанию держит кэш в памяти процесса (LocMemCache). Под
gunicorn это три независимых кэша: счётчик попыток входа (ТЗ п.7.7)
делится между воркерами, и «5 попыток за 10 минут» превращается в 15,
а после перезапуска контейнера обнуляется совсем. Тот же счётчик нужен
и для заявок с опубликованных сайтов, и для общего лимита API.

Поэтому в развёртывании кэш берётся из Valkey: он уже поднят в compose,
и его же позже займут фоновые задачи. Valkey, а не Redis, — из-за
лицензии (ТЗ п.7.1.6); протокол тот же, поэтому клиент — redis-py (MIT).

Пустой VALKEY_URL оставляет LocMemCache: тесты и запуск без Docker
обязаны работать офлайн и без внешних сервисов (ТЗ п.16.4). Это не
ослабление поставки: compose задаёт адрес всегда, а боевой контур без
общего кэша не поднимается.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Схемы, которые понимает клиент. Valkey протокол-совместим с Redis,
#: но redis-py проверяет схему и отвергает всё, кроме своих: `valkey://`
#: даёт ValueError ещё до первого подключения.
SCHEMES = {
    'valkey': 'redis',
    'valkeys': 'rediss',
    'redis': 'redis',
    'rediss': 'rediss',
    'unix': 'unix',
}

#: Таймауты по умолчанию. Без них redis-py ждёт ответа бесконечно: если
#: Valkey недоступен, каждый запрос к API повисает вместо быстрой
#: ошибки, и платформа «висит» целиком, хотя упал только кэш.
DEFAULT_TIMEOUT_SECONDS = 1


def cache_settings(valkey_url: str) -> dict:
    """Настройка CACHES по адресу Valkey.

    Пустой адрес — LocMemCache. Неизвестная схема — ошибка запуска, а не
    тихая работа без общего счётчика: опечатка в `VALKEY_URL` иначе
    выглядела бы как исправная установка, в которой лимит втрое слабее.
    """
    url = (valkey_url or '').strip()
    if not url:
        return {
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'aurabuilder',
            },
        }

    parts = urlsplit(url)
    scheme = SCHEMES.get(parts.scheme)
    if scheme is None:
        raise RuntimeError(
            'VALKEY_URL принимает схемы valkey://, redis:// или unix://, '
            f'получено: {parts.scheme!r}',
        )
    if not parts.netloc and scheme != 'unix':
        raise RuntimeError(f'VALKEY_URL без адреса сервера: {url!r}')

    # Параметры в адресе главнее умолчаний: на медленном канале стенда
    # одну секунду можно поднять, не трогая код.
    query = dict(parse_qsl(parts.query))
    query.setdefault('socket_timeout', str(DEFAULT_TIMEOUT_SECONDS))
    query.setdefault(
        'socket_connect_timeout', str(DEFAULT_TIMEOUT_SECONDS),
    )

    return {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': urlunsplit((
                scheme, parts.netloc, parts.path, urlencode(query), '',
            )),
            # Префикс отделяет счётчики платформы от ключей Celery:
            # общий Valkey иначе смешал бы пространства имён.
            'KEY_PREFIX': 'aurabuilder',
        },
    }


__all__ = ['DEFAULT_TIMEOUT_SECONDS', 'SCHEMES', 'cache_settings']
