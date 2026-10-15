"""Telegram Mini App (ТЗ п.16.6).

Проверяется то, на чём держится доверие к приложению: подпись
initData, срок жизни данных, права на подключение бота и то, что
токен бота не покидает платформу.
"""

from __future__ import annotations

import json
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from billing.models import Subscription
from projects.models import Project
from publications.models import Site
from secretstore.crypto import generate_key
from telegram import api as telegram_api
from telegram.bot_api import BotIdentity
from telegram.auth import (
    EDGE_TOKEN_TTL,
    EdgeTokenInvalid,
    issue_edge_token,
    read_edge_token,
)
from telegram.initdata import (
    InitDataInvalid,
    MAX_AUTH_AGE,
    TelegramUser,
    expected_hash,
    parse_init_data,
    secret_key,
    sign,
    verify,
    verify_signature,
)
from telegram.models import TelegramBot

User = get_user_model()

#: Ключ шифрования: токен бота — такой же чужой секрет, как пароль.
TEST_KEY = generate_key('test')

#: Тестовый токен: настоящий не существует и не должен проверяться.
TOKEN = '123456:AAHtest-token-value'

#: Подпись настоящего бота в тестах не проверяется — она вычисляется.
USER_JSON = json.dumps({
    'id': 424242,
    'username': 'ivan',
    'first_name': 'Иван',
    'last_name': 'Петров',
    'language_code': 'ru',
    'is_premium': True,
}, ensure_ascii=False, separators=(',', ':'))


def make_init_data(token: str = TOKEN, *, auth_date: int | None = None,
                   user: str = USER_JSON, **extra) -> str:
    params = {
        'auth_date': str(auth_date if auth_date is not None
                         else int(time.time())),
        'query_id': 'AAHd6-1',
        'user': user,
    }
    params.update(extra)
    return sign(params, token)


class SignatureTests(TestCase):
    def test_signature_matches_documented_scheme(self):
        params = {'auth_date': '1700000000', 'user': USER_JSON}
        expected = expected_hash(TOKEN, params)
        signed = sign(params, TOKEN)
        self.assertEqual(parse_init_data(signed)['hash'], expected)

    def test_secret_key_is_sha256_of_token(self):
        import hashlib
        self.assertEqual(secret_key(TOKEN),
                         hashlib.sha256(TOKEN.encode()).digest())

    def test_data_check_string_excludes_hash_and_sorts(self):
        params = parse_init_data(make_init_data())
        check = '\n'.join(sorted(f'{k}={v}' for k, v in params.items()
                                 if k != 'hash'))
        self.assertNotIn('hash', check)
        self.assertEqual(check.split('\n')[0].split('=')[0], 'auth_date')

    def test_valid_init_data_is_accepted(self):
        user, params = verify(make_init_data(), TOKEN)
        self.assertIsInstance(user, TelegramUser)
        self.assertEqual(user.id, 424242)
        self.assertEqual(user.display_name, 'Иван Петров')
        self.assertEqual(params['query_id'], 'AAHd6-1')

    def test_wrong_token_is_refused(self):
        with self.assertRaises(InitDataInvalid):
            verify_signature(make_init_data(), '999:другой-токен')

    def test_tampered_user_is_refused(self):
        signed = parse_init_data(make_init_data())
        signed['user'] = json.dumps({'id': 1, 'first_name': 'Чужой'})
        from urllib.parse import urlencode
        with self.assertRaises(InitDataInvalid):
            verify_signature(urlencode(signed), TOKEN)

    def test_missing_hash_is_refused(self):
        with self.assertRaises(InitDataInvalid):
            verify_signature('auth_date=1700000000&user=%7B%7D', TOKEN)

    def test_empty_init_data_is_refused(self):
        with self.assertRaises(InitDataInvalid):
            verify('   ', TOKEN)


class FreshnessTests(TestCase):
    def test_old_data_is_refused(self):
        old = int(time.time()) - MAX_AUTH_AGE - 120
        with self.assertRaises(InitDataInvalid):
            verify(make_init_data(auth_date=old), TOKEN)

    def test_fresh_data_is_accepted(self):
        user, _ = verify(make_init_data(auth_date=int(time.time()) - 60),
                         TOKEN)
        self.assertEqual(user.id, 424242)

    def test_time_from_the_future_is_refused(self):
        ahead = int(time.time()) + 3600
        with self.assertRaises(InitDataInvalid):
            verify(make_init_data(auth_date=ahead), TOKEN)

    def test_missing_auth_date_is_refused(self):
        with self.assertRaises(InitDataInvalid):
            verify('user=%7B%22id%22%3A1%7D&hash=x', TOKEN)


class UserParsingTests(TestCase):
    def test_user_json_survives_ampersands(self):
        # Имя с «&» не должно разорвать параметр: иначе подпись
        # проверялась бы для обрезанного значения.
        tricky = json.dumps({'id': 7, 'first_name': 'A&B'},
                            ensure_ascii=False, separators=(',', ':'))
        user, _ = verify(make_init_data(user=tricky), TOKEN)
        self.assertEqual(user.first_name, 'A&B')

    def test_broken_user_is_refused(self):
        with self.assertRaises(InitDataInvalid):
            verify(make_init_data(user='не json'), TOKEN)

    def test_user_without_id_is_refused(self):
        with self.assertRaises(InitDataInvalid):
            verify(make_init_data(user='{"first_name":"X"}'), TOKEN)


class EdgeTokenTests(TestCase):
    def test_token_carries_bot_and_project(self):
        from telegram.auth import issue_edge_token

        raw = issue_edge_token(telegram_user_id=42, bot_username='shop_bot',
                               project_id='abc')
        claims = read_edge_token(raw)
        self.assertEqual(claims.telegram_user_id, 42)
        self.assertEqual(claims.bot, 'shop_bot')
        self.assertEqual(claims.project, 'abc')

    def test_forged_token_is_refused(self):
        body, _, signature = issue_edge_token(
            telegram_user_id=1, bot_username='shop_bot',
            project_id='abc').partition('.')
        tampered = '.'.join([body[:-2] + 'XY', signature])
        with self.assertRaises(EdgeTokenInvalid):
            read_edge_token(tampered)

    def test_expired_token_is_refused(self):
        old = int(time.time()) - EDGE_TOKEN_TTL - 10
        raw = issue_edge_token(telegram_user_id=1, bot_username='b',
                               project_id='p', now=old)
        with self.assertRaises(EdgeTokenInvalid):
            read_edge_token(raw)


@override_settings(LOGIN_ATTEMPT_LIMIT=1000,
                   DJANGO_SECRET_ENCRYPTION_KEYS=TEST_KEY,
                   PLATFORM_BASE_URL='https://aura.example')
class BotApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        Subscription.objects.create(user=self.owner, plan='pro')
        self.editor = User.objects.create_user('editor', password='pass-ed')
        self.project = Project.objects.create(owner=self.owner, name='Магазин')

    def client_for(self, user, password: str) -> APIClient:
        # Вход возвращает пару токенов, и клиент обязан предъявить их
        # в заголовке: без него запрос считается анонимным.
        client = APIClient()
        response = client.post('/api/auth/login/',
                               {'login': user.username, 'password': password},
                               format='json')
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}'
        )
        return client

    def make_bot(self, username: str = 'shop_bot') -> TelegramBot:
        bot = TelegramBot(project=self.project, owner=self.owner,
                          name='Магазин в Telegram', bot_username=username)
        bot.set_token(TOKEN)
        bot.save()
        return bot

    def create_via_api(self, client, *, identity=None, verifier=None,
                       **overrides):
        # Проверка токена подменяется аргументом, а не внутри: иначе
        # подмена самого теста не влияла бы на вызов, и тест проверял
        # бы успешный путь вместо отказа.
        identity = identity or BotIdentity(777, 'shop_bot')
        payload = {'name': 'Магазин', 'botUsername': 'shop_bot',
                   'token': TOKEN}
        payload.update(overrides)
        patcher = (mock.patch.object(telegram_api, 'verify_token',
                                     side_effect=verifier)
                   if verifier else
                   mock.patch.object(telegram_api, 'verify_token',
                                     return_value=identity))
        with patcher:
            return client.post(
                f'/api/projects/{self.project.id}/telegram-bot/',
                payload, format='json',
            )


class BotApiTests(BotApiTestCase):
    def test_owner_connects_bot(self):
        response = self.create_via_api(self.client_for(self.owner, 'pass-owner'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['botUsername'], 'shop_bot')
        self.assertEqual(response.data['botId'], 777)
        self.assertTrue(response.data['hasToken'])

    def test_token_is_never_returned(self):
        response = self.create_via_api(self.client_for(self.owner, 'pass-owner'))
        self.assertNotIn(TOKEN, json.dumps(response.data))
        listing = self.client_for(self.owner, 'pass-owner').get(
            f'/api/projects/{self.project.id}/telegram-bot/')
        self.assertNotIn(TOKEN, json.dumps(listing.data))

    def test_token_is_encrypted_in_database(self):
        self.create_via_api(self.client_for(self.owner, 'pass-owner'))
        bot = TelegramBot.objects.get(bot_username='shop_bot')
        self.assertNotIn(TOKEN, bot.token_encrypted)
        self.assertEqual(bot.get_token(), TOKEN)

    def test_free_plan_is_refused(self):
        Subscription.objects.filter(user=self.owner).update(plan='free')
        response = self.create_via_api(self.client_for(self.owner, 'pass-owner'))
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()['reason'], 'tariff_denied')

    def test_editor_cannot_connect_bot(self):
        # 404, а не 403: редактор не участник проекта, и ответ не
        # должен подтверждать, что проект существует.
        response = self.create_via_api(self.client_for(self.editor, 'pass-ed'))
        self.assertEqual(response.status_code, 404)

    def test_outside_token_is_refused(self):
        # Telegram не признаёт токен: сохранять его незачем, деплой
        # упрётся в ошибку только при первом же вызове.
        response = self.create_via_api(
            self.client_for(self.owner, 'pass-owner'), token='не-токен',
            verifier=telegram_api.BotApiError('Bad Request: Unauthorized'),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            TelegramBot.objects.filter(bot_username='shop_bot').exists())

    def test_wrong_login_is_refused(self):
        response = self.create_via_api(self.client_for(self.owner, 'pass-owner'),
                                       botUsername='other_bot')
        self.assertEqual(response.status_code, 400)
        self.assertIn('@shop_bot', json.dumps(response.data))

    def test_missing_fields_are_refused(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = client.post(
            f'/api/projects/{self.project.id}/telegram-bot/',
            {'name': 'Без токена'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_duplicate_login_is_conflict(self):
        self.make_bot()
        response = self.create_via_api(self.client_for(self.owner, 'pass-owner'))
        self.assertEqual(response.status_code, 409)

    def test_outsider_sees_nothing(self):
        self.make_bot()
        outsider = User.objects.create_user('outsider', password='pass-x')
        response = self.client_for(outsider, 'pass-x').get(
            f'/api/projects/{self.project.id}/telegram-bot/')
        self.assertEqual(response.status_code, 404)


class BotManagementTests(BotApiTestCase):
    def test_menu_is_configured(self):
        bot = self.make_bot()
        with mock.patch.object(telegram_api, 'set_web_app_menu') as setter:
            setter.return_value = {}
            response = self.client_for(self.owner, 'pass-owner').post(
                f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/menu/',
                {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['menuConfigured'])
        url = setter.call_args.args[1]
        self.assertEqual(url, 'https://aura.example/telegram/shop_bot/')

    def test_menu_failure_is_reported_and_not_marked(self):
        bot = self.make_bot()
        with mock.patch.object(telegram_api, 'set_web_app_menu',
                               side_effect=telegram_api.BotApiError('Telegram недоступен')):
            response = self.client_for(self.owner, 'pass-owner').post(
                f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/menu/',
                {}, format='json')
        self.assertEqual(response.status_code, 502)
        bot.refresh_from_db()
        self.assertIsNone(bot.menu_configured_at)

    def test_menu_without_token_is_conflict(self):
        bot = TelegramBot(project=self.project, owner=self.owner,
                          name='Без токена', bot_username='no_token_bot')
        bot.save()
        response = self.client_for(self.owner, 'pass-owner').post(
            f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/menu/',
            {}, format='json')
        self.assertEqual(response.status_code, 409)

    def test_new_token_resets_menu_mark(self):
        bot = self.make_bot()
        from django.utils import timezone
        bot.menu_configured_at = timezone.now()
        bot.save()
        with mock.patch.object(telegram_api, 'verify_token',
                               return_value=BotIdentity(777,
                                                                'shop_bot')):
            self.client_for(self.owner, 'pass-owner').patch(
                f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/',
                {'token': '999:другой-токен'}, format='json')
        bot.refresh_from_db()
        self.assertIsNone(bot.menu_configured_at)
        self.assertEqual(bot.get_token(), '999:другой-токен')

    def test_bot_is_deleted(self):
        bot = self.make_bot()
        response = self.client_for(self.owner, 'pass-owner').delete(
            f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(TelegramBot.objects.filter(pk=bot.pk).exists())

    def test_links_are_built_for_botfather(self):
        bot = self.make_bot()
        public = bot.public_dict()
        self.assertEqual(public['startAppLink'],
                         'https://t.me/shop_bot')
        self.assertEqual(public['miniAppUrl'],
                         'https://aura.example/telegram/shop_bot/')


class MiniAppAuthTests(BotApiTestCase):
    def test_valid_init_data_returns_edge_token(self):
        bot = self.make_bot()
        response = APIClient().post('/api/telegram/auth/', {
            'bot': 'shop_bot', 'initData': make_init_data(),
        }, format='json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['user']['id'], 424242)
        self.assertEqual(body['project']['id'], str(self.project.id))
        claims = read_edge_token(body['token'])
        self.assertEqual(claims.bot, 'shop_bot')
        self.assertEqual(claims.telegram_user_id, 424242)

    def test_foreign_init_data_is_refused(self):
        self.make_bot()
        response = APIClient().post('/api/telegram/auth/', {
            'bot': 'shop_bot',
            'initData': make_init_data('999:чужой-токен'),
        }, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['reason'], 'init_data_invalid')

    def test_unknown_bot_is_404(self):
        response = APIClient().post('/api/telegram/auth/', {
            'bot': 'no_such_bot', 'initData': make_init_data(),
        }, format='json')
        self.assertEqual(response.status_code, 404)

    def test_bot_without_token_is_not_distinguishable(self):
        # Ответ «нет токена» выдавал бы посетителю, какие логины
        # подключены, а какие нет.
        TelegramBot.objects.create(project=self.project, owner=self.owner,
                                   name='Пустой', bot_username='empty_bot')
        response = APIClient().post('/api/telegram/auth/', {
            'bot': 'empty_bot', 'initData': make_init_data(),
        }, format='json')
        self.assertEqual(response.status_code, 404)

    def test_missing_init_data_is_400(self):
        self.make_bot()
        response = APIClient().post('/api/telegram/auth/', {'bot': 'shop_bot'},
                                   format='json')
        self.assertEqual(response.status_code, 400)

    @override_settings(DJANGO_SECRET_ENCRYPTION_KEYS='')
    def test_without_encryption_key_token_is_not_stored(self):
        client = self.client_for(self.owner, 'pass-owner')
        with mock.patch.object(telegram_api, 'verify_token',
                               return_value=BotIdentity(1, 'shop_bot')):
            response = client.post(
                f'/api/projects/{self.project.id}/telegram-bot/',
                {'name': 'Бот', 'botUsername': 'shop_bot', 'token': TOKEN},
                format='json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['reason'], 'no_encryption_key')


class MiniAppPageTests(BotApiTestCase):
    def test_page_shows_project(self):
        from projects.versions import snapshot

        tree = {'width': 1200, 'blocks': [{
            'id': 'b1', 'module': 'text.heading', 'x': 0, 'y': 0,
            'width': 600, 'height': 120,
            'props': {'text': 'Кафе «Уют»'},
        }]}
        self.project.tree = tree
        self.project.save()
        snapshot(self.project, tree, author=self.owner, label='v1')

        self.make_bot()
        response = APIClient().get('/telegram/shop_bot/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('Кафе «Уют»', body)
        self.assertIn('Telegram', body)
        self.assertNotIn(TOKEN, body)

    def test_published_site_link_is_shown(self):
        from projects.versions import snapshot
        from publications.service import publish

        version = snapshot(self.project, self.project.tree,
                           author=self.owner, label='v1')
        publish(self.project, version)
        self.make_bot()

        response = APIClient().get('/telegram/shop_bot/')
        body = response.content.decode('utf-8')
        self.assertIn('/sites/', body)
        self.assertIn('Опубликованный сайт', body)

    def test_unknown_bot_is_404(self):
        self.assertEqual(
            APIClient().get('/telegram/nope_bot/').status_code, 404)

    def test_page_without_connection_says_so(self):
        self.assertEqual(
            APIClient().get('/telegram/nope_bot/').status_code, 404)

    def test_url_name_resolves(self):
        self.assertEqual(reverse('telegram-mini-app',
                                 args=['shop_bot']),
                         '/telegram/shop_bot/')