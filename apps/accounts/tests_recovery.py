"""Восстановление пароля и удаление аккаунта (ТЗ п.13.1).

Проверяются свойства, на которых держится доверие: ссылка из письма
одноразовая, ограничена по времени и не хранится в базе; ответ на
запрос не выдаёт, существует ли аккаунт; удаление уносит данные и
требует пароль.
"""

from __future__ import annotations

import hashlib

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.emails import (
    FAILOVER_THRESHOLD,
    failures,
    on_failover,
    reset_password_body,
    send_mail,
)
from accounts.models import AuditLog, PasswordReset

User = get_user_model()

REQUEST_URL = '/api/auth/password-reset/request/'
CONFIRM_URL = '/api/auth/password-reset/confirm/'
DELETE_URL = '/api/auth/me/delete/'


def key_from_mail() -> str:
    """Ключ из ссылки в письме.

    Список писем берётся здесь, а не в аргументе по умолчанию: значение
    по умолчанию вычисляется при импорте модуля, когда тестовое
    окружение ещё не поднято, и ссылалось бы на пустой список.
    """
    body = mail.outbox[-1].body
    start = body.index('token=') + len('token=')
    end = body.index('\n', start)
    return body[start:end].strip()


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class PasswordResetRequestTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            'owner', 'owner@example.com', 'verysecret12345',
        )

    def test_link_is_sent(self):
        response = self.client.post(REQUEST_URL,
                                    {'email': 'owner@example.com'},
                                    format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('восстанов', mail.outbox[0].subject.lower())
        self.assertEqual(mail.outbox[0].to, ['owner@example.com'])

    def test_answer_is_same_for_unknown_email(self):
        known = self.client.post(REQUEST_URL,
                                 {'email': 'owner@example.com'}, format='json')
        cache.clear()
        mail.outbox.clear()
        unknown = self.client.post(REQUEST_URL,
                                   {'email': 'nobody@example.com'},
                                   format='json')
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(len(mail.outbox), 0)

    def test_answer_does_not_reveal_existence(self):
        body = self.client.post(REQUEST_URL, {'email': 'nobody@example.com'},
                                format='json').json()
        self.assertNotIn('nobody@example.com', str(body))
        self.assertNotIn('owner@example.com', str(body))

    def test_key_is_not_stored(self):
        self.client.post(REQUEST_URL, {'email': 'owner@example.com'},
                         format='json')
        key = key_from_mail()
        stored = PasswordReset.objects.get()
        self.assertNotEqual(stored.key_hash, key)
        self.assertEqual(
            stored.key_hash,
            hashlib.sha256(key.encode('utf-8')).hexdigest(),
        )

    def test_previous_keys_are_revoked(self):
        self.client.post(REQUEST_URL, {'email': 'owner@example.com'},
                         format='json')
        first = key_from_mail()
        self.client.post(REQUEST_URL, {'email': 'owner@example.com'},
                         format='json')
        self.assertTrue(PasswordReset.objects.get(key_hash=(
            hashlib.sha256(first.encode()).hexdigest())).used_at)

    def test_invalid_email_is_400(self):
        response = self.client.post(REQUEST_URL, {'email': 'не-адрес'},
                                    format='json')
        self.assertEqual(response.status_code, 400)

    def test_ip_is_recorded(self):
        response = self.client.post(
            REQUEST_URL, {'email': 'owner@example.com'}, format='json',
            REMOTE_ADDR='203.0.113.7')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordReset.objects.get().requested_ip,
                         '203.0.113.7')


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class PasswordResetConfirmTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            'owner', 'owner@example.com', 'verysecret12345',
        )
        self.client.post(REQUEST_URL, {'email': 'owner@example.com'},
                         format='json')
        self.key = key_from_mail()

    def confirm(self, password='newverysecret123', key=None):
        return self.client.post(CONFIRM_URL,
                                {'token': key or self.key, 'password': password},
                                format='json')

    def test_password_is_changed(self):
        response = self.confirm()
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newverysecret123'))
        self.assertIn('access', response.json())

    def test_key_is_single_use(self):
        self.assertEqual(self.confirm().status_code, 200)
        second = self.confirm(password='anothersecret12345')
        self.assertEqual(second.status_code, 400)
        self.assertIn('уже использован', second.json()['detail'])

    def test_expired_key_is_refused(self):
        PasswordReset.objects.update(
            expires_at=timezone.now() - timezone.timedelta(minutes=1))
        response = self.confirm()
        self.assertEqual(response.status_code, 400)
        self.assertIn('истёк', response.json()['detail'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('verysecret12345'))

    def test_wrong_key_is_refused(self):
        response = self.confirm(key='подделка')
        self.assertEqual(response.status_code, 400)
        self.assertIn('недействительна', response.json()['detail'])

    def test_weak_password_is_refused(self):
        response = self.confirm(password='коротк')
        self.assertEqual(response.status_code, 400)
        # Проверяется результат, а не формулировка: пароль не сменился,
        # а текст Django меняется от версии к версии.
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('verysecret12345'))

    def test_old_sessions_are_closed(self):
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
        )
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(self.user)
        jti = str(refresh['jti'])
        self.confirm()
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=jti).exists())


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class AccountDeleteTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            'owner', 'owner@example.com', 'verysecret12345',
        )
        self.login()

    def login(self, password='verysecret12345'):
        # Вход возвращает пару токенов, и клиент обязан предъявить её
        # в заголовке: без этого следующий запрос анонимный.
        response = self.client.post('/api/auth/login/',
                                    {'login': 'owner', 'password': password},
                                    format='json')
        if response.status_code == 200:
            self.client.credentials(
                HTTP_AUTHORIZATION='Bearer ' + response.data['access']
            )

    def test_anonymous_is_refused(self):
        self.assertEqual(APIClient().delete(
            DELETE_URL, {'password': 'verysecret12345', 'confirm': True},
            format='json').status_code, 401)

    def test_wrong_password_is_refused(self):
        response = self.client.delete(DELETE_URL,
                                      {'password': 'не тот', 'confirm': True},
                                      format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_confirmation_is_required(self):
        response = self.client.delete(
            DELETE_URL, {'password': 'verysecret12345', 'confirm': False},
            format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_projects_require_separate_confirmation(self):
        from projects.models import Project

        Project.objects.create(owner=self.user, name='Магазин')
        response = self.client.delete(
            DELETE_URL, {'password': 'verysecret12345', 'confirm': True},
            format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['reason'], 'confirm_projects')
        self.assertEqual(response.json()['projects'], ['Магазин'])
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_project_with_coauthor_cannot_be_deleted_silently(self):
        from accounts.models import Membership, Role
        from projects.models import Project

        project = Project.objects.create(owner=self.user, name='Общий')
        other = User.objects.create_user('teammate', password='pass-team')
        Membership.objects.create(project=project, user=other,
                                  role=Role.EDITOR)
        response = self.client.delete(
            DELETE_URL, {'password': 'verysecret12345', 'confirm': True,
                         'withProjects': True}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['reason'], 'shared_projects')
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())

    def test_account_and_data_are_deleted(self):
        from projects.models import Project

        project = Project.objects.create(owner=self.user, name='Магазин')
        response = self.client.delete(
            DELETE_URL, {'password': 'verysecret12345', 'confirm': True,
                         'withProjects': True}, format='json')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())

    def test_old_password_stops_working(self):
        self.client.delete(DELETE_URL,
                           {'password': 'verysecret12345', 'confirm': True,
                            'withProjects': True}, format='json')
        self.login()
        response = self.client.get('/api/auth/me/')
        self.assertIn(response.status_code, (401, 403))

    def test_deletion_is_written_to_audit(self):
        self.client.delete(DELETE_URL,
                           {'password': 'verysecret12345', 'confirm': True,
                            'withProjects': True}, format='json')
        action = AuditLog.objects.values_list('action', flat=True)
        self.assertIn('account.deleted', action)


class EmailFailoverTests(TestCase):
    """Фейловер на локальный relay после трёх ошибок подряд (п.13.1)."""

    def setUp(self):
        cache.clear()
        mail.outbox.clear()

    def test_no_failover_before_threshold(self):
        self.assertFalse(on_failover())
        self.assertEqual(failures(), 0)

    def test_three_failures_switch_channel(self):
        for index in range(FAILOVER_THRESHOLD - 1):
            cache.set('email:failures', index + 1)
            self.assertFalse(on_failover(), index)
        cache.set('email:failures', FAILOVER_THRESHOLD)
        self.assertTrue(on_failover())

    def test_success_on_primary_resets_counter(self):
        # Счётчик обнуляется только когда основной канал снова
        # работает: письмо, ушедшее через резерв, счёт не сбрасывает.
        cache.set('email:failures', 1)
        send_mail('тема', 'текст', ['owner@example.com'])
        self.assertEqual(failures(), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_relay_success_keeps_counter(self):
        cache.set('email:failures', FAILOVER_THRESHOLD)
        send_mail('тема', 'текст', ['owner@example.com'])
        self.assertEqual(failures(), FAILOVER_THRESHOLD)
        self.assertEqual(len(mail.outbox), 1)

    def test_mail_goes_to_relay_when_failover(self):
        cache.set('email:failures', FAILOVER_THRESHOLD)
        result = send_mail('тема', 'текст', ['owner@example.com'])
        self.assertTrue(result)
        self.assertEqual(result.channel, 'fallback')
        self.assertEqual(len(mail.outbox), 1)

    def test_broken_primary_is_reported(self):
        from accounts import emails

        # Основной канал поднимается как исключение: считаем, что
        # счётчик ошибок мал и резерва ещё нет.
        original = emails._connection

        def boom(alias='default'):
            raise OSError('SMTP недоступен')

        emails._connection = boom
        try:
            result = emails.send_mail('тема', 'текст', ['a@example.com'])
        finally:
            emails._connection = original
        self.assertFalse(result)
        self.assertEqual(result.channel, 'primary')
        self.assertEqual(failures(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_body_mentions_ttl_and_single_use(self):
        body = reset_password_body('https://aura/reset?token=abc', 60)
        self.assertIn('60 минут', body)
        self.assertIn('один раз', body)
        self.assertIn('token=abc', body)


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class UrlTests(TestCase):
    def test_routes_exist(self):
        self.assertEqual(reverse('password-reset-request'), REQUEST_URL)
        self.assertEqual(reverse('password-reset-confirm'), CONFIRM_URL)
        self.assertEqual(reverse('account-delete'), DELETE_URL)