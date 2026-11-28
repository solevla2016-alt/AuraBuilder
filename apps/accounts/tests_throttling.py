"""Кого считает ограничение частоты и где живёт его счётчик.

Здесь закреплены две дыры, найденные аудитом перед выпуском:

* `X-Forwarded-For` присылает сам клиент. Если брать первый адрес из
  заголовка, лимит обходится сменой заголовка, а в журнале остаётся
  чужой IP.
* `LocMemCache` живёт в памяти процесса. У gunicorn три воркера, и
  «5 попыток за 10 минут» превращаются в 15, а после перезапуска
  счётчик обнуляется.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from controlplane.caching import cache_settings

from .serializers import get_client_ip

User = get_user_model()


class ClientIpTests(SimpleTestCase):
    """Адрес берётся с конца заголовка: начало пишет сам клиент."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_forged_prefix_is_ignored(self):
        request = self.factory.get(
            '/', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.7',
        )
        self.assertEqual(get_client_ip(request), '203.0.113.7')

    def test_each_trusted_proxy_is_counted(self):
        request = self.factory.get(
            '/', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.7, 198.51.100.1',
        )
        with override_settings(TRUSTED_PROXY_COUNT=2):
            self.assertEqual(get_client_ip(request), '203.0.113.7')

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_proxy_the_header_is_ignored(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='6.6.6.6')
        self.assertEqual(get_client_ip(request), '127.0.0.1')

    def test_missing_header_falls_back_to_remote_addr(self):
        request = self.factory.get('/')
        self.assertEqual(get_client_ip(request), '127.0.0.1')


class LoginThrottleKeyTests(APITestCase):
    """Лимит входа считается по адресу, а не по заголовку или токену."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'target', 'target@example.com', 'verysecret123',
        )

    def attempt(self, forwarded: str | None = None):
        extra = {}
        if forwarded is not None:
            extra['HTTP_X_FORWARDED_FOR'] = forwarded
        return self.client.post(
            '/api/auth/login/',
            {'login': 'target', 'password': 'wrong'},
            format='json',
            **extra,
        )

    def test_forged_prefix_does_not_reset_counter(self):
        for index in range(5):
            response = self.attempt(f'203.0.113.{index}, 198.51.100.7')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Шестая попытка с новым подделанным началом — тот же настоящий
        # адрес, значит тот же счётчик.
        response = self.attempt('203.0.113.200, 198.51.100.7')
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
        )

    def test_token_does_not_get_separate_counter(self):
        for _ in range(5):
            self.assertEqual(
                self.attempt().status_code, status.HTTP_400_BAD_REQUEST,
            )
        # Токен своего аккаунта не должен открывать новое окно: иначе
        # с одним аккаунтом можно перебирать пароли чужих без предела.
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(
            self.attempt().status_code, status.HTTP_429_TOO_MANY_REQUESTS,
        )


class CacheSettingsTests(SimpleTestCase):
    """Кэш общий на воркеры, если задан Valkey, и локальный без него."""

    def test_without_url_stays_in_process(self):
        config = cache_settings('')
        self.assertEqual(
            config['default']['BACKEND'],
            'django.core.cache.backends.locmem.LocMemCache',
        )

    def test_valkey_scheme_becomes_redis(self):
        # redis-py не принимает valkey://, хотя протокол тот же.
        location = cache_settings(
            'valkey://cache:6379/0',
        )['default']['LOCATION']
        self.assertTrue(location.startswith('redis://cache:6379/0?'))
        self.assertIn('socket_timeout=1', location)

    def test_timeouts_from_url_are_kept(self):
        location = cache_settings(
            'redis://cache:6379/0?socket_timeout=5',
        )['default']['LOCATION']
        self.assertIn('socket_timeout=5', location)
        self.assertNotIn('socket_timeout=1', location)

    def test_unknown_scheme_stops_startup(self):
        # Опечатка в адресе не должна выглядеть как исправная установка
        # с ослабленным лимитом.
        with self.assertRaises(RuntimeError):
            cache_settings('http://cache:6379/0')

    def test_api_uses_the_same_proxy_count(self):
        self.assertEqual(api_settings.NUM_PROXIES, settings.TRUSTED_PROXY_COUNT)
