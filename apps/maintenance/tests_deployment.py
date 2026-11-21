"""Режимы развёртывания: cloud и self-hosted (ТЗ п.16.4).

Проверяется не «включён ли флаг», а поведение, которое видит человек:
закрытая регистрация отвечает отказом до валидации формы, тарифные
проверки в self-hosted не мешают владельцу установки, а экран входа
узнаёт режим до авторизации.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from billing.service import (
    check_page_slot,
    check_project_slot,
    check_record_count,
    check_scenario,
    plan_for,
)
from projects.models import Project

User = get_user_model()

SELF_HOSTED = dict(
    DEPLOYMENT_MODE='self-hosted',
    REGISTRATION_OPEN=False,
    BILLING_ENABLED=False,
)

REGISTER_PAYLOAD = {
    'username': 'newcomer',
    'email': 'newcomer@example.com',
    'password': 'Auraduilder-2026-Newcomer',
    'consent_pdn': True,
}


class ConfigEndpointTests(TestCase):
    def test_cloud_config_is_public_and_open(self):
        response = self.client.get('/api/config/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'mode': 'cloud', 'registrationOpen': True, 'billingEnabled': True},
        )

    @override_settings(**SELF_HOSTED)
    def test_self_hosted_hides_registration_and_billing(self):
        response = self.client.get('/api/config/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'mode': 'self-hosted',
                'registrationOpen': False,
                'billingEnabled': False,
            },
        )


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class RegistrationModeTests(TestCase):
    def setUp(self):
        # Окно входа общее на процесс: без сброса соседние тесты могли
        # израсходовать лимит, и проверка режима падала бы с 429 вместо
        # 403/201, не имея отношения к регистрации.
        cache.clear()

    @override_settings(**SELF_HOSTED)
    def test_self_hosted_rejects_registration_before_validation(self):
        # Пароль заведомо короткий: если бы проверка стояла после
        # валидации, ответ был бы 400 про пароль, а не 403 о режиме.
        payload = dict(REGISTER_PAYLOAD, password='short')

        response = self.client.post(
            '/api/auth/register/', payload, content_type='application/json'
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Регистрация', response.json()['detail'])
        self.assertFalse(User.objects.filter(username='newcomer').exists())

    def test_cloud_still_accepts_registration(self):
        response = self.client.post(
            '/api/auth/register/', REGISTER_PAYLOAD, content_type='application/json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username='newcomer').exists())


class SelfHostedBillingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='owner', password='Auraduilder-2026-Owner'
        )
        Project.objects.create(owner=self.user, name='Единственный')

    @override_settings(BILLING_ENABLED=False)
    def test_no_tariff_limits_inside_own_installation(self):
        # На Free проект был бы уже вторым, а записей — больше лимита.
        self.assertEqual(plan_for(self.user).code, 'business')
        self.assertIsNone(check_project_slot(self.user))
        self.assertIsNone(check_page_slot(self.user, 10_000))
        self.assertIsNone(check_record_count(self.user, 10_000))
        for scenario in (1, 2, 3, 4, 5):
            self.assertIsNone(check_scenario(self.user, scenario), scenario)

    def test_cloud_keeps_free_limits(self):
        self.assertEqual(plan_for(self.user).code, 'free')
        self.assertIsNotNone(check_project_slot(self.user))
        self.assertIsNotNone(check_scenario(self.user, 4))
