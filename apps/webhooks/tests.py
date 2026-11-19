"""Вебхуки: подписки, подпись и журнал доставок.

Проверяется поведение, а не наличие кода: подходящий вебхук получает
событие с проверяемой подписью, неподходящий — нет, сбой приёмника не
ломает публикацию, а повтор ограничен и не оживляет выключенные
подписки.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership, Role
from projects.events import record
from projects.models import Project, ProjectEvent
from webhooks.models import (
    MAX_ATTEMPTS,
    MAX_DELIVERIES,
    MAX_WEBHOOKS,
    Webhook,
    WebhookDelivery,
)
from webhooks.service import payload_body, sign

User = get_user_model()


class WebhookBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            'owner', 'owner@example.com', 'owner-pass-123',
        )
        self.project = Project.objects.create(name='Сайт', owner=self.owner)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token("owner", "owner-pass-123")}',
        )
        self.url = f'/api/projects/{self.project.id}/webhooks/'

    def _token(self, login: str, password: str) -> str:
        response = self.client.post(
            '/api/auth/login/', {'login': login, 'password': password},
            format='json',
        )
        return response.data['access']

    def _client(self, username: str, role: str):
        user = User.objects.create_user(username, password='member-pass')
        Membership.objects.create(
            project=self.project, user=user, role=role,
        )
        client = self.client_class()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token(username, "member-pass")}',
        )
        return client

    def _create_hook(self, url='https://example.com/hook', events=None,
                     active=True) -> Webhook:
        return Webhook.objects.create(
            project=self.project,
            url=url,
            events=events or [],
            active=active,
        )

    def _delivery(self, hook) -> WebhookDelivery:
        return hook.deliveries.first()


class WebhookApiTests(WebhookBase):
    def test_list_returns_event_catalog_and_limit(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['limit'], MAX_WEBHOOKS)
        self.assertEqual(
            [item['id'] for item in response.data['events']],
            [value for value, _label in ProjectEvent.KIND_CHOICES],
        )
        self.assertEqual(response.data['webhooks'], [])

    def test_only_integration_managers_manage(self):
        editor = self._client('editor', Role.EDITOR)
        self.assertEqual(
            editor.get(self.url).status_code, status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            editor.post(self.url, {'url': 'https://example.com/h'},
                        format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )

        developer = self._client('developer', Role.DEV)
        created = developer.post(
            self.url, {'url': 'https://example.com/h'}, format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED,
                         created.data)

    def test_stranger_does_not_see_project(self):
        stranger = User.objects.create_user('stranger', password='stranger-pass')
        client = self.client_class()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token("stranger", "stranger-pass")}',
        )
        self.assertEqual(
            client.get(self.url).status_code, status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(stranger.username, 'stranger')

    def test_create_validates_address(self):
        for url in ('', 'ftp://example.com/h', 'javascript:alert(1)',
                    'example.com/hook'):
            response = self.client.post(self.url, {'url': url}, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                             url)

    def test_create_returns_secret_and_can_be_deleted(self):
        created = self.client.post(
            self.url, {'url': 'https://example.com/hook'}, format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED,
                         created.data)
        self.assertTrue(created.data['active'])
        self.assertEqual(created.data['events'], [])
        self.assertGreaterEqual(len(created.data['secret']), 32)

        listing = self.client.get(self.url)
        self.assertEqual(len(listing.data['webhooks']), 1)

        removed = self.client.delete(
            f'{self.url}{created.data["id"]}/',
        )
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.project.webhooks.count(), 0)

    def test_limit_is_enforced(self):
        for index in range(MAX_WEBHOOKS):
            self._create_hook(url=f'https://example.com/{index}')
        response = self.client.post(
            self.url, {'url': 'https://example.com/extra'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_unknown_event_is_refused(self):
        response = self.client.post(
            self.url,
            {'url': 'https://example.com/h', 'events': ['publish', 'no-such']},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_changes_address_events_and_state(self):
        hook = self._create_hook(events=['publish'])
        response = self.client.patch(
            f'{self.url}{hook.id}/',
            {'url': 'https://example.com/new', 'events': [],
             'active': False},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        hook.refresh_from_db()
        self.assertEqual(hook.url, 'https://example.com/new')
        self.assertEqual(hook.events, [])
        self.assertFalse(hook.active)

    def test_rotation_changes_secret(self):
        hook = self._create_hook()
        old = hook.secret
        response = self.client.post(f'{self.url}{hook.id}/rotate/')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        hook.refresh_from_db()
        self.assertNotEqual(hook.secret, old)

    def test_foreign_project_is_hidden(self):
        other = Project.objects.create(name='Чужой', owner=self.owner)
        foreign = Webhook.objects.create(project=other, url='https://e.com/h')
        response = self.client.get(f'{self.url}{foreign.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_source_of_another_project_is_hidden(self):
        other = Project.objects.create(name='Чужой', owner=self.owner)
        foreign = Webhook.objects.create(
            project=other, url='https://example.com/foreign',
        )
        response = self.client.delete(f'{self.url}{foreign.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Webhook.objects.filter(pk=foreign.pk).exists())


class DeliveryTests(WebhookBase):
    def test_event_reaches_matching_hook_with_signature(self):
        hook = self._create_hook(events=[])
        with mock.patch('webhooks.service._post',
                        return_value=(202, '')) as post:
            event = record(
                self.project, ProjectEvent.KIND_PUBLISH, 'Сайт опубликован',
            )

        self.assertIsNotNone(event)
        self.assertEqual(post.call_count, 1)
        url, body, headers = post.call_args.args
        self.assertEqual(url, hook.url)
        self.assertEqual(headers['X-Aura-Event'], ProjectEvent.KIND_PUBLISH)
        self.assertEqual(
            headers['X-Aura-Signature'], sign(hook.secret, body),
        )
        expected = hmac.new(
            hook.secret.encode('utf-8'), body, hashlib.sha256,
        ).hexdigest()
        self.assertEqual(headers['X-Aura-Signature'], f'sha256={expected}')

        payload = json.loads(body)
        self.assertEqual(payload['event']['kind'], ProjectEvent.KIND_PUBLISH)
        self.assertEqual(payload['event']['message'], 'Сайт опубликован')
        self.assertEqual(payload['project']['name'], 'Сайт')
        self.assertEqual(headers['X-Aura-Delivery'], payload['delivery'])

        delivery = self._delivery(hook)
        self.assertEqual(delivery.status, WebhookDelivery.STATUS_OK)
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.response_code, 202)
        self.assertIsNotNone(delivery.delivered_at)

    def test_hook_with_selected_events_is_selective(self):
        selected = self._create_hook(url='https://example.com/pub',
                                     events=[ProjectEvent.KIND_PUBLISH])
        everything = self._create_hook(url='https://example.com/all',
                                       events=[])
        with mock.patch('webhooks.service._post', return_value=(200, '')):
            record(self.project, ProjectEvent.KIND_DEPLOY, 'Выложено')
            record(self.project, ProjectEvent.KIND_PUBLISH, 'Опубликовано')

        self.assertEqual(selected.deliveries.count(), 1)
        self.assertEqual(
            self._delivery(selected).event_kind, ProjectEvent.KIND_PUBLISH,
        )
        self.assertEqual(everything.deliveries.count(), 2)

    def test_inactive_hook_receives_nothing(self):
        hook = self._create_hook(active=False)
        with mock.patch('webhooks.service._post', return_value=(200, '')) as post:
            record(self.project, ProjectEvent.KIND_PUBLISH, 'Опубликовано')
        post.assert_not_called()
        self.assertEqual(hook.deliveries.count(), 0)

    def test_failed_delivery_does_not_break_event(self):
        hook = self._create_hook()
        with mock.patch('webhooks.service._post',
                        return_value=(500, 'HTTP 500: Server Error')):
            event = record(
                self.project, ProjectEvent.KIND_DEPLOY, 'Ошибка выкладки',
            )

        self.assertIsNotNone(event)
        self.assertTrue(ProjectEvent.objects.filter(pk=event.pk).exists())
        delivery = self._delivery(hook)
        self.assertEqual(delivery.status, WebhookDelivery.STATUS_FAILED)
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.response_code, 500)
        self.assertEqual(delivery.error, 'HTTP 500: Server Error')
        self.assertIsNone(delivery.delivered_at)

    def test_delivery_history_is_bounded(self):
        hook = self._create_hook()
        with mock.patch('webhooks.service.MAX_DELIVERIES', 2), \
                mock.patch('webhooks.service._post', return_value=(200, '')):
            for index in range(4):
                record(self.project, ProjectEvent.KIND_BUILD,
                       f'Сборка {index}')
        self.assertEqual(hook.deliveries.count(), 2)

    def test_manual_retry_ignores_automatic_limit(self):
        hook = self._create_hook()
        delivery = WebhookDelivery.objects.create(
            webhook=hook,
            event_kind=ProjectEvent.KIND_PUBLISH,
            payload={'event': {'kind': ProjectEvent.KIND_PUBLISH}},
            attempts=MAX_ATTEMPTS,
        )
        with mock.patch('webhooks.service._post', return_value=(204, '')):
            response = self.client.post(
                f'{self.url}{hook.id}/deliveries/{delivery.id}/retry/',
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.STATUS_OK)
        self.assertEqual(delivery.attempts, MAX_ATTEMPTS + 1)

    def test_retry_command_respects_attempt_limit(self):
        hook = self._create_hook()
        retryable = WebhookDelivery.objects.create(
            webhook=hook,
            event_kind=ProjectEvent.KIND_BUILD,
            payload={'event': {'kind': ProjectEvent.KIND_BUILD}},
            attempts=1,
        )
        exhausted = WebhookDelivery.objects.create(
            webhook=hook,
            event_kind=ProjectEvent.KIND_BUILD,
            payload={'event': {'kind': ProjectEvent.KIND_BUILD}},
            attempts=MAX_ATTEMPTS,
        )
        with mock.patch('webhooks.service._post', return_value=(200, '')):
            call_command('retry_webhooks', stdout=io.StringIO())

        retryable.refresh_from_db()
        exhausted.refresh_from_db()
        self.assertEqual(retryable.status, WebhookDelivery.STATUS_OK)
        self.assertEqual(retryable.attempts, 2)
        self.assertEqual(exhausted.attempts, MAX_ATTEMPTS)
        self.assertEqual(exhausted.status, WebhookDelivery.STATUS_FAILED)

    def test_retry_command_skips_disabled_hooks(self):
        hook = self._create_hook(active=False)
        delivery = WebhookDelivery.objects.create(
            webhook=hook,
            event_kind=ProjectEvent.KIND_BUILD,
            payload={},
            attempts=1,
        )
        with mock.patch('webhooks.service._post', return_value=(200, '')) as post:
            call_command('retry_webhooks', stdout=io.StringIO())
        post.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.STATUS_FAILED)


class SignatureTests(WebhookBase):
    def test_signature_matches_manual_hmac(self):
        body = payload_body({'event': {'kind': 'publish'}})
        digest = hmac.new(
            b's3cret', body, hashlib.sha256,
        ).hexdigest()
        self.assertEqual(sign('s3cret', body), f'sha256={digest}')

    def test_signature_changes_with_secret_and_body(self):
        body = b'{"a":1}'
        self.assertNotEqual(sign('one', body), sign('two', body))
        self.assertNotEqual(sign('one', body), sign('one', b'{"a":2}'))
