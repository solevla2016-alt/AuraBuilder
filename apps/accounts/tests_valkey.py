"""Живая проверка общего кэша на Valkey.

Файл запускается только при заданном `VALKEY_URL`: без него кэш
локальный, и проверять нечего. В CI рядом поднят сервис valkey, поэтому
здесь проходит весь путь «настройки → redis-py → сервер», а не только
разбор конфигурации. Именно этот путь ломается при переезде со
LocMemCache и не виден остальным тестам: они работают на кэше процесса.

Тест не очищает базу целиком: ключи уникальны для каждого запуска.
`cache.clear()` на общем стенде стёр бы счётчики работающих воркеров.
"""

from __future__ import annotations

import os
import uuid
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.cache.backends.redis import RedisCache
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase, APIRequestFactory

from .throttling import LoginRateThrottle

User = get_user_model()

#: Без живого сервера проверка бессмысленна: LocMemCache прошёл бы её
#: и без Valkey, ничего не доказав.
NEEDS_VALKEY = skipUnless(
    os.environ.get('VALKEY_URL'),
    'нужен живой Valkey: задайте VALKEY_URL',
)


def second_client() -> RedisCache:
    """Второй клиент с теми же настройками — как у соседнего воркера."""
    config = settings.CACHES['default']
    return RedisCache(
        config['LOCATION'],
        {'KEY_PREFIX': config.get('KEY_PREFIX', '')},
    )


@NEEDS_VALKEY
class ValkeyCacheTests(SimpleTestCase):
    def setUp(self):
        # Заодно проверяется приведение valkey:// к redis://: без него
        # redis-py отказывается подключаться ещё до первого запроса.
        self.assertTrue(
            settings.CACHES['default']['LOCATION'].startswith('redis://'),
            settings.CACHES['default']['LOCATION'],
        )

    def test_value_survives_a_new_client(self):
        key = f'aurabuilder:probe-{uuid.uuid4().hex}'
        cache.set(key, 'ok', 30)
        try:
            # Значение читает другой клиент: оно на сервере, а не в
            # памяти процесса, — значит счётчик общий для воркеров.
            self.assertEqual(second_client().get(key), 'ok')
        finally:
            cache.delete(key)


@NEEDS_VALKEY
class SharedLoginCounterTests(APITestCase):
    """Счётчик попыток входа лежит там, где его увидит любой воркер."""

    def setUp(self):
        User.objects.create_user(
            'target', 'target@example.com', 'verysecret123',
        )
        # Свой «адрес» на запуск: ключ лимита уникален, чистить базу
        # целиком не нужно.
        self.address = f'test-{uuid.uuid4().hex}'

    def attempt(self):
        return self.client.post(
            '/api/auth/login/',
            {'login': 'target', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR=self.address,
        )

    def test_counter_is_visible_to_another_worker(self):
        for _ in range(5):
            self.assertEqual(
                self.attempt().status_code, status.HTTP_400_BAD_REQUEST,
            )

        # Ключ считаем тем же кодом, что и второй воркер, и читаем
        # другим клиентом: счётчик физически в Valkey.
        throttle = LoginRateThrottle()
        throttle.scope = 'login'
        request = APIRequestFactory().post(
            '/api/auth/login/', REMOTE_ADDR=self.address,
        )
        key = throttle.get_cache_key(request, None)
        history = second_client().get(key)
        self.assertIsNotNone(history, f'ключ {key} не найден в Valkey')
        self.assertEqual(len(history), 5)

        self.assertEqual(
            self.attempt().status_code, status.HTTP_429_TOO_MANY_REQUESTS,
        )
