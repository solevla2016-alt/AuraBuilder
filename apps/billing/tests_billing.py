"""Проверка правил тарификации (ТЗ п.17.1).

Тесты проверяют не «вернёлся ли 403», а право: одна шкала тарифов,
одна проверка сценария, один счётчик проектов. Если тест проходит, а
пользователь всё равно упёрся в лимит, значит ограничение в другом
месте и не покрыто здесь.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from projects.models import Project

from .models import Subscription
from .plans import PLANS, covers, get_plan, rank
from .service import (
    Denial,
    check_page_slot,
    check_project_slot,
    check_record_count,
    check_scenario,
    plan_for,
)

User = get_user_model()


def projects_of(user) -> int:
    """Сколько проектов у пользователя.

    Связь названа owned_projects: проекты, где он участник, тарифом
    не ограничиваются — платит владелец.
    """
    return Project.objects.filter(owner=user).count()


def denial_slot(user) -> Denial:
    """Причина отказа в проекте; падает, если отказа нет."""
    denial = check_project_slot(user)
    assert denial is not None, 'ожидался отказ по лимиту проектов'
    return denial


class PlanScaleTests(TestCase):
    def test_tariffs_follow_the_spec_order(self):
        self.assertEqual(
            [PLANS[code].price for code in ('free', 'start', 'pro', 'business')],
            [0, 990, 2490, 7990],
        )

    def test_free_has_only_publication_and_backup(self):
        free = PLANS['free']
        self.assertTrue(free.allows(1))
        self.assertTrue(free.allows(5))
        self.assertFalse(free.allows(2))
        self.assertFalse(free.allows(3))
        self.assertFalse(free.allows(4))

    def test_start_allows_export_and_deploy_but_not_pwa(self):
        start = PLANS['start']
        for scenario in (1, 2, 3, 5):
            self.assertTrue(start.allows(scenario), scenario)
        self.assertFalse(start.allows(4))

    def test_pro_and_business_allow_everything(self):
        for code in ('pro', 'business'):
            plan = PLANS[code]
            for scenario in range(1, 6):
                self.assertTrue(plan.allows(scenario), f'{code}/{scenario}')

    def test_business_has_no_numeric_limits(self):
        business = PLANS['business']
        self.assertIsNone(business.max_projects)
        self.assertIsNone(business.max_pages)
        self.assertIsNone(business.max_records)

    def test_pro_allows_one_onedc_base(self):
        self.assertTrue(PLANS['pro'].onedc_integration)
        self.assertFalse(PLANS['start'].onedc_integration)

    def test_unknown_plan_falls_back_to_free_not_to_top(self):
        self.assertIs(get_plan('enterprise').code, 'free')
        self.assertIs(get_plan('').code, 'free')

    def test_covers_compares_by_scale_position(self):
        self.assertTrue(covers('pro', 'start'))
        self.assertTrue(covers('start', 'start'))
        self.assertFalse(covers('free', 'start'))
        self.assertEqual(rank('business'), 3)


class ScenarioGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='owner', email='owner@example.com', password='x',
        )

    def test_without_subscription_user_is_free(self):
        self.assertIsNone(getattr(self.user, 'subscription', None))
        self.assertIs(plan_for(self.user).code, 'free')

    def test_free_denies_export_with_named_minimum(self):
        denial = check_scenario(self.user, 2)
        self.assertIsInstance(denial, Denial)
        self.assertIn('Start', denial.detail)
        self.assertIn('990', denial.detail)

    def test_free_denies_deploy_and_telegram(self):
        self.assertIsNotNone(check_scenario(self.user, 3))
        self.assertIsNotNone(check_scenario(self.user, 4))

    def test_free_allows_publication_and_backup_on_any_tariff(self):
        Subscription.objects.create(user=self.user, plan='free')
        self.assertIsNone(check_scenario(self.user, 1))
        self.assertIsNone(check_scenario(self.user, 5))

    def test_start_opens_export_and_keeps_telegram_closed(self):
        Subscription.objects.create(user=self.user, plan='start')
        self.assertIsNone(check_scenario(self.user, 2))
        self.assertIsNone(check_scenario(self.user, 3))
        self.assertIn('Pro', check_scenario(self.user, 4).detail)

    def test_inactive_subscription_falls_back_to_free(self):
        Subscription.objects.create(user=self.user, plan='pro', active=False)
        self.assertIs(plan_for(self.user).code, 'free')
        self.assertIsNotNone(check_scenario(self.user, 2))


class PendingPlanTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='owner2', email='owner2@example.com', password='x',
        )
        self.subscription = Subscription.objects.create(
            user=self.user, plan='pro',
        )

    def test_pending_plan_is_invisible_before_the_deadline(self):
        self.subscription.pending_plan = 'start'
        self.subscription.pending_since = timezone.now()
        self.subscription.save()
        self.assertIs(plan_for(self.user).code, 'pro')

    def test_pending_plan_applies_after_a_day(self):
        self.subscription.pending_plan = 'start'
        self.subscription.pending_since = timezone.now() - timedelta(days=1,
                                                                 seconds=1)
        self.subscription.save()
        self.assertIs(plan_for(self.user).code, 'start')

    def test_applying_folds_pending_into_plan(self):
        self.subscription.pending_plan = 'free'
        self.subscription.pending_since = timezone.now() - timedelta(hours=25)
        self.subscription.save()
        self.assertTrue(self.subscription.apply_pending_if_due())
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, 'free')
        self.assertEqual(self.subscription.pending_plan, '')

    def test_apply_before_deadline_changes_nothing(self):
        self.subscription.pending_plan = 'free'
        self.subscription.pending_since = timezone.now()
        self.subscription.save()
        self.assertFalse(self.subscription.apply_pending_if_due())
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, 'pro')


class LimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='owner3', email='owner3@example.com', password='x',
        )
        self.project = Project.objects.create(
            owner=self.user, name='Первый',
        )

    def test_free_allows_exactly_one_project(self):
        # Проект из setUp уже есть: второй Free не позволяет.
        self.assertIsNotNone(check_project_slot(self.user))
        self.assertIn('1', denial_slot(self.user).detail)

    def test_start_allows_five_projects(self):
        Subscription.objects.create(user=self.user, plan='start')
        for index in range(2, 6):
            Project.objects.create(owner=self.user, name=f'Проект {index}')
        self.assertEqual(projects_of(self.user), 5)
        Project.objects.create(owner=self.user, name='Шестой')
        self.assertIsNotNone(check_project_slot(self.user))

    def test_business_never_blocks_projects(self):
        Subscription.objects.create(user=self.user, plan='business')
        for index in range(30):
            Project.objects.create(owner=self.user, name=f'Проект {index}')
        self.assertIsNone(check_project_slot(self.user))

    def test_projects_of_someone_else_do_not_count(self):
        other = User.objects.create_user(
            username='stranger', email='stranger@example.com', password='x',
        )
        Project.objects.create(owner=other, name='Чужой')
        self.assertEqual(projects_of(self.user), 1)
        self.assertEqual(projects_of(other), 1)
        # Свой проект уже есть, лимит Free — один: чужой проект не
        # изменил счёт, но и не добавил его.
        self.assertEqual(projects_of(self.user), 1)

    def test_page_limit_counts_pages_not_blocks(self):
        self.assertIsNone(check_page_slot(self.user, 5))
        self.assertIsNotNone(check_page_slot(self.user, 6))

    def test_record_limit_follows_the_plan(self):
        self.assertIsNone(check_record_count(self.user, 20))
        self.assertIsNotNone(check_record_count(self.user, 21))
        Subscription.objects.create(user=self.user, plan='pro')
        self.assertIsNone(check_record_count(self.user, 10_000))
        self.assertIsNotNone(check_record_count(self.user, 10_001))


@override_settings(SECURE_SSL_REDIRECT=False)
class SubscriptionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='owner4', email='owner4@example.com', password='pw',
        )
        self.client.force_authenticate(self.user)

    def test_anonymous_is_refused(self):
        self.assertEqual(
            APIClient().get('/api/billing/subscription/').status_code, 401,
        )

    def test_free_plan_and_availability_are_reported(self):
        response = self.client.get('/api/billing/subscription/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['plan']['code'], 'free')
        self.assertEqual(body['available'], {
            '1': True, '2': False, '3': False, '4': False, '5': True,
        })
        self.assertEqual(len(body['plans']), 4)

    def test_change_plan_applies_immediately(self):
        response = self.client.post(
            '/api/billing/subscription/change/', {'plan': 'start'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['plan']['code'], 'start')
        self.assertTrue(check_scenario(self.user, 2) is None)

    def test_unknown_plan_is_rejected(self):
        response = self.client.post(
            '/api/billing/subscription/change/', {'plan': 'enterprise'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_secret_billing_key_is_never_exposed(self):
        body = self.client.get('/api/billing/subscription/').json()
        self.assertNotIn('secret', repr(body))