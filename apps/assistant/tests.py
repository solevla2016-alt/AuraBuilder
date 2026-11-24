"""ИИ-помощник: кредиты, локальные подсказки и API.

Тесты проверяют расход, а не наличие кода: кредиты списываются один
раз и только за удачный ответ, чужой проект не виден, наблюдатель не
тратит кредиты владельца. Локальный провайдер проверяется отдельно —
он работает без сети и обязан давать осмысленную структуру, а не
пустой ответ.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership, Role
from billing.models import Subscription
from billing.plans import PLANS
from projects.models import Project
from projects.module_registry import MODULE_IDS
from publications.models import Site

from . import credits
from .actions import ACTIONS
from .models import AiRequest, CreditPeriod
from .providers import (
    LocalProvider,
    ProviderError,
    get_provider,
    parse_model_text,
    provider_code,
    provider_info,
)

User = get_user_model()


def make_project(owner, name='Сайт') -> Project:
    return Project.objects.create(name=name, owner=owner)


class CreditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'owner', 'owner@example.com', 'owner-pass-123',
        )

    def test_free_plan_starts_with_twenty_credits(self):
        state = credits.status_for(self.user)
        self.assertEqual(state['used'], 0)
        self.assertEqual(state['limit'], 20)
        self.assertEqual(state['remaining'], 20)
        self.assertEqual(
            state['period'], credits.current_period(),
        )

    def test_spend_moves_used_and_remaining(self):
        state = credits.spend(self.user, 3)
        self.assertEqual(state['used'], 3)
        self.assertEqual(state['remaining'], 17)
        self.assertEqual(credits.used_credits(self.user), 3)

    def test_spend_is_cumulative(self):
        credits.spend(self.user, 3)
        state = credits.spend(self.user, 1)
        self.assertEqual(state['used'], 4)
        self.assertEqual(state['remaining'], 16)

    def test_spend_over_limit_raises_and_changes_nothing(self):
        CreditPeriod.objects.create(
            user=self.user, period=credits.current_period(), used=19,
        )
        with self.assertRaises(credits.InsufficientCredits) as caught:
            credits.spend(self.user, 3)
        self.assertEqual(caught.exception.used, 19)
        self.assertEqual(caught.exception.limit, 20)
        self.assertEqual(credits.used_credits(self.user), 19)

    def test_credits_are_separate_for_different_users(self):
        other = User.objects.create_user('other', password='other-pass-123')
        credits.spend(self.user, 3)
        self.assertEqual(credits.used_credits(other), 0)

    def test_previous_month_is_not_counted(self):
        previous = timezone.localdate().replace(day=1) - timedelta(days=1)
        CreditPeriod.objects.create(
            user=self.user,
            period=f'{previous.year:04d}-{previous.month:02d}',
            used=20,
        )
        state = credits.status_for(self.user)
        self.assertEqual(state['used'], 0)
        self.assertEqual(state['remaining'], 20)

    def test_reset_date_is_first_day_of_next_month(self):
        state = credits.status_for(self.user, period='2026-12')
        self.assertEqual(state['resets_at'], '2027-01-01')

    def test_business_has_no_credit_limit_but_usage_is_tracked(self):
        Subscription.objects.create(user=self.user, plan='business')
        self.assertIsNone(credits.limit_for(self.user))
        state = credits.spend(self.user, 3)
        self.assertIsNone(state['limit'])
        self.assertIsNone(state['remaining'])
        self.assertEqual(state['used'], 3)

    @override_settings(BILLING_ENABLED=False)
    def test_self_hosted_has_no_credit_limit(self):
        state = credits.status_for(self.user)
        self.assertIsNone(state['limit'])
        self.assertIsNone(state['remaining'])
        state = credits.spend(self.user, 3)
        self.assertEqual(state['used'], 3)

    def test_plan_scale_declares_credits_for_every_tariff(self):
        self.assertEqual(PLANS['free'].ai_credits, 20)
        self.assertEqual(PLANS['start'].ai_credits, 300)
        self.assertEqual(PLANS['pro'].ai_credits, 2000)
        self.assertIsNone(PLANS['business'].ai_credits)


class LocalProviderTests(TestCase):
    def setUp(self):
        self.provider = LocalProvider()
        self.action = ACTIONS['page_outline']

    def test_outline_follows_keywords(self):
        result = self.provider.generate(
            self.action,
            'Лендинг студии ремонта с преимуществами, тарифами, '
            'этапами работы и формой заявки.',
            {'project': 'Ремонт'},
        )
        modules = [item['module'] for item in result.items]
        self.assertEqual(modules[0], 'section.hero')
        self.assertIn('section.feature', modules)
        self.assertIn('promo.pricing', modules)
        self.assertIn('section.steps', modules)
        self.assertIn('action.form', modules)
        self.assertEqual(modules[-1], 'section.footer')
        self.assertIn('секций', result.summary)
        self.assertEqual(result.provider, 'local')

    def test_outline_without_keywords_still_gives_a_structure(self):
        result = self.provider.generate(
            self.action, 'Просто красивый сайт', {},
        )
        modules = [item['module'] for item in result.items]
        self.assertIn('section.feature', modules)
        self.assertIn('text.paragraph', modules)
        self.assertEqual(modules[-1], 'section.footer')

    def test_outline_does_not_invent_modules(self):
        result = self.provider.generate(
            self.action,
            'Магазин с каталогом, отзывами, галереей, командой и FAQ',
            {},
        )
        for item in result.items:
            self.assertIn(item['module'], MODULE_IDS)

    def test_catalog_schema_uses_data_source_field_types(self):
        result = self.provider.generate(
            ACTIONS['data_schema'],
            'Каталог мебели с ценой, категорией, фотографией и складом.',
            {},
        )
        fields = {item['key']: item for item in result.items}
        self.assertEqual(fields['price']['type'], 'number')
        self.assertEqual(fields['image']['type'], 'image')
        self.assertTrue(fields['name']['required'])
        self.assertIn('published', fields)

    def test_request_schema_requires_consent(self):
        result = self.provider.generate(
            ACTIONS['data_schema'],
            'Форма заявки на замер с телефона.',
            {},
        )
        fields = {item['key']: item for item in result.items}
        self.assertTrue(fields['consent']['required'])
        self.assertEqual(fields['consent']['type'], 'boolean')

    def test_review_unpublished_project_starts_with_publication(self):
        result = self.provider.generate(
            ACTIONS['project_review'], '',
            {'project': 'Сайт', 'pages': 1, 'records': 0,
             'published': False},
        )
        self.assertIn('не было', result.summary)
        self.assertIn('Опубликуйте', result.items[0]['title'])
        self.assertTrue(any('источник данных' in item['title'].lower()
                            for item in result.items))

    def test_review_with_records_suggests_showing_them(self):
        result = self.provider.generate(
            ACTIONS['project_review'], '',
            {'project': 'Сайт', 'pages': 3, 'records': 12,
             'published': True},
        )
        self.assertTrue(any(
            item.get('module') == 'data.collection'
            for item in result.items
        ))
        self.assertIn('опубликован', result.summary)


class ParseModelTests(TestCase):
    def test_parses_json_in_code_fence(self):
        summary, items = parse_model_text(
            '```json\n{"summary": "План", "items": '
            '[{"title": "Первый экран", "module": "section.hero"}]}\n```'
        )
        self.assertEqual(summary, 'План')
        self.assertEqual(items[0]['module'], 'section.hero')

    def test_plain_text_becomes_summary(self):
        summary, items = parse_model_text('Просто ответ без JSON')
        self.assertEqual(summary, 'Просто ответ без JSON')
        self.assertEqual(items, [])

    def test_unknown_item_keys_are_dropped(self):
        _, items = parse_model_text(
            '{"summary": "x", "items": ['
            '{"title": "A", "secret": "nope", "required": true}]}'
        )
        self.assertNotIn('secret', items[0])
        self.assertTrue(items[0]['required'])


class ProviderConfigTests(TestCase):
    @override_settings(AI_PROVIDER='auto', YANDEX_GPT_API_KEY='',
                       YANDEX_GPT_FOLDER_ID='')
    def test_auto_without_key_uses_local(self):
        self.assertEqual(provider_code(), 'local')
        self.assertIsInstance(get_provider(), LocalProvider)

    @override_settings(AI_PROVIDER='auto', YANDEX_GPT_API_KEY='key',
                       YANDEX_GPT_FOLDER_ID='folder')
    def test_auto_with_key_uses_yandex(self):
        self.assertEqual(provider_code(), 'yandex')
        self.assertNotIsInstance(get_provider(), LocalProvider)

    @override_settings(AI_PROVIDER='yandex', YANDEX_GPT_API_KEY='',
                       YANDEX_GPT_FOLDER_ID='')
    def test_explicit_yandex_without_key_is_an_error(self):
        info = provider_info()
        self.assertFalse(info['ready'])
        self.assertTrue(info['external'])
        with self.assertRaises(ProviderError):
            get_provider()


class AssistantApiBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            'owner', 'owner@example.com', 'owner-pass-123',
        )
        self.project = make_project(self.owner)
        self.url = f'/api/projects/{self.project.id}/assistant/'
        self.run_url = f'{self.url}run/'
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token("owner", "owner-pass-123")}',
        )

    def _token(self, login: str, password: str) -> str:
        response = self.client.post(
            '/api/auth/login/', {'login': login, 'password': password},
            format='json',
        )
        return response.data['access']

    def _member(self, username: str, role: str):
        user = User.objects.create_user(username, password='member-pass-123')
        Membership.objects.create(
            project=self.project, user=user, role=role,
        )
        client = self.client_class()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token(username, "member-pass-123")}',
        )
        return user, client


class AssistantApiTests(AssistantApiBase):
    def test_status_lists_actions_credits_and_provider(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['credits']['limit'], 20)
        self.assertEqual(response.data['credits']['used'], 0)
        self.assertTrue(response.data['can_edit'])
        self.assertEqual(response.data['provider']['code'], 'local')
        codes = [item['code'] for item in response.data['actions']]
        self.assertEqual(codes, ['page_outline', 'data_schema',
                                 'project_review'])
        costs = {item['code']: item['cost']
                 for item in response.data['actions']}
        self.assertEqual(costs['page_outline'], 3)
        self.assertEqual(costs['project_review'], 1)
        self.assertEqual(response.data['recent'], [])

    def test_run_spends_credits_and_writes_journal(self):
        response = self.client.post(
            self.run_url,
            {'action': 'page_outline',
             'description': 'Лендинг с преимуществами и формой заявки.'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['credits']['used'], 3)
        self.assertEqual(response.data['credits']['remaining'], 17)
        self.assertEqual(response.data['result']['provider'], 'local')
        self.assertTrue(response.data['result']['items'])

        row = AiRequest.objects.get()
        self.assertEqual(row.user, self.owner)
        self.assertEqual(row.actor, self.owner)
        self.assertEqual(row.project, self.project)
        self.assertEqual(row.action, 'page_outline')
        self.assertEqual(row.credits, 3)
        self.assertIn('Лендинг', row.prompt)

        history = self.client.get(self.url).data['recent']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['action_title'], 'План страницы')
        self.assertNotIn('prompt', history[0])

    def test_unknown_action_is_rejected(self):
        response = self.client.post(
            self.run_url,
            {'action': 'write_text', 'description': 'Что-нибудь'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['reason'], 'invalid_input')
        self.assertEqual(credits.used_credits(self.owner), 0)

    def test_short_description_does_not_spend_credits(self):
        response = self.client.post(
            self.run_url,
            {'action': 'page_outline', 'description': 'Сайт'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(credits.used_credits(self.owner), 0)
        self.assertEqual(AiRequest.objects.count(), 0)

    def test_project_review_does_not_need_a_description(self):
        response = self.client.post(
            self.run_url, {'action': 'project_review'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['credits']['used'], 1)

    def test_review_sees_publication_state(self):
        Site.objects.create(project=self.project, slug='site')
        response = self.client.post(
            self.run_url, {'action': 'project_review'}, format='json',
        )
        self.assertIn('опубликован', response.data['result']['summary'])

    def test_exhausted_credits_return_402_without_journal(self):
        CreditPeriod.objects.create(
            user=self.owner, period=credits.current_period(), used=20,
        )
        response = self.client.post(
            self.run_url, {'action': 'project_review'}, format='json',
        )
        self.assertEqual(
            response.status_code, status.HTTP_402_PAYMENT_REQUIRED,
        )
        self.assertEqual(response.data['reason'], 'credits_exhausted')
        self.assertEqual(response.data['credits']['remaining'], 0)
        self.assertEqual(AiRequest.objects.count(), 0)

    @override_settings(AI_PROVIDER='yandex', YANDEX_GPT_API_KEY='',
                       YANDEX_GPT_FOLDER_ID='')
    def test_unconfigured_provider_returns_502_and_keeps_credits(self):
        response = self.client.post(
            self.run_url, {'action': 'project_review'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data['reason'], 'provider_unavailable')
        self.assertEqual(credits.used_credits(self.owner), 0)

    def test_viewer_reads_status_but_cannot_spend_owner_credits(self):
        _user, client = self._member('viewer', Role.VIEWER)
        status_response = client.get(self.url)
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertFalse(status_response.data['can_edit'])
        self.assertTrue(all(
            not item['available'] for item in status_response.data['actions']
        ))

        response = client.post(
            self.run_url, {'action': 'project_review'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(credits.used_credits(self.owner), 0)
        self.assertEqual(AiRequest.objects.count(), 0)

    def test_editor_spends_owner_credits_and_is_named_in_journal(self):
        Subscription.objects.create(user=self.owner, plan='pro')
        editor, client = self._member('editor', Role.EDITOR)
        response = client.post(
            self.run_url, {'action': 'project_review'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['credits']['used'], 1)
        self.assertEqual(credits.used_credits(self.owner), 1)
        self.assertEqual(credits.used_credits(editor), 0)
        row = AiRequest.objects.get()
        self.assertEqual(row.user, self.owner)
        self.assertEqual(row.actor, editor)

    def test_outsider_cannot_read_status(self):
        outsider = User.objects.create_user(
            'outsider', password='outsider-pass-123',
        )
        client = self.client_class()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token("outsider", "outsider-pass-123")}',
        )
        response = client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(BILLING_ENABLED=False)
    def test_self_hosted_status_has_no_credit_limit(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['credits']['limit'])
        self.assertFalse(response.data['billing_enabled'])

    def test_subscription_contract_includes_ai_quota(self):
        response = self.client.get('/api/billing/subscription/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['plan']['ai_credits'], 20)
        self.assertEqual(
            response.data['usage']['ai'], {'used': 0, 'limit': 20},
        )
