"""События проекта и уведомления Telegram.

Проверяется то, ради чего это сделано: событие остаётся в журнале даже
при недоступном Telegram, уведомление уходит только в привязанный чат, а
привязка не требует вводить chat_id вручную. Отдельно — что чужой
человек не видит ленту проекта и не может перенаправить уведомления на
себя.
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Membership, Role
from billing.models import Subscription
from projects.events import KEEP_EVENTS, record, recent
from projects.models import Project, ProjectEvent
from secretstore.crypto import generate_key
from telegram.bot_api import BotApiError, latest_chat, send_message
from telegram.models import TelegramBot
from telegram.notifications import format_event

User = get_user_model()

TEST_KEY = generate_key('test')
TOKEN = '123456:AAHtest-token-value'

PRIVATE_CHAT = {
    'id': 555,
    'type': 'private',
    'first_name': 'Иван',
    'last_name': 'Петров',
}

GROUP_CHAT = {'id': -777, 'type': 'group', 'title': 'Рабочий чат'}


def update(chat: dict, update_id: int = 1) -> dict:
    return {
        'update_id': update_id,
        'message': {'message_id': update_id, 'text': '/start', 'chat': chat},
    }


@override_settings(
    LOGIN_ATTEMPT_LIMIT=1000,
    DJANGO_SECRET_ENCRYPTION_KEYS=TEST_KEY,
    PLATFORM_BASE_URL='https://aura.example',
)
class EventBase(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        Subscription.objects.create(user=self.owner, plan='pro')
        self.project = Project.objects.create(owner=self.owner, name='Цветы')

    def client_for(self, user, password: str) -> APIClient:
        client = APIClient()
        response = client.post(
            '/api/auth/login/',
            {'login': user.username, 'password': password},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}',
        )
        return client

    def make_bot(self, *, chat_id: int | None = None,
                 username: str = 'shop_bot') -> TelegramBot:
        bot = TelegramBot(
            project=self.project, owner=self.owner,
            name='Магазин в Telegram', bot_username=username,
        )
        bot.set_token(TOKEN)
        if chat_id is not None:
            bot.notify_chat_id = chat_id
            bot.notify_chat_title = 'Иван'
        bot.save()
        return bot


class EventJournalTests(EventBase):
    def test_event_is_stored_with_human_fields(self):
        event = record(
            self.project, ProjectEvent.KIND_PUBLISH,
            'Сайт опубликован.', status=ProjectEvent.STATUS_OK,
            actor=self.owner,
        )
        self.assertIsNotNone(event)
        payload = event.public_dict()
        self.assertEqual(payload['kindLabel'], 'Публикация')
        self.assertEqual(payload['actor'], 'owner')
        self.assertEqual(payload['status'], 'ok')
        self.assertTrue(payload['createdAt'])

    def test_recent_is_newest_first(self):
        record(self.project, ProjectEvent.KIND_BUILD, 'первое')
        record(self.project, ProjectEvent.KIND_PUBLISH, 'второе')
        messages = [event.message for event in recent(self.project)]
        self.assertEqual(messages[:2], ['второе', 'первое'])

    def test_old_events_are_pruned(self):
        with mock.patch('projects.events.KEEP_EVENTS', 2):
            for index in range(4):
                record(self.project, ProjectEvent.KIND_BUILD, f'сборка {index}')
        self.assertEqual(ProjectEvent.objects.filter(project=self.project).count(), 2)
        self.assertGreaterEqual(KEEP_EVENTS, 2)

    def test_notification_failure_does_not_break_record(self):
        # Журнал обязан сохранить событие, даже если Telegram упал:
        # операция к этому моменту уже выполнена.
        with mock.patch(
            'telegram.notifications.notify_event',
            side_effect=RuntimeError('нет сети'),
        ):
            event = record(self.project, ProjectEvent.KIND_DEPLOY, 'деплой')
        self.assertIsNotNone(event)
        self.assertTrue(ProjectEvent.objects.filter(pk=event.pk).exists())

    def test_events_endpoint_returns_feed(self):
        record(self.project, ProjectEvent.KIND_PUBLISH, 'Сайт опубликован.',
               status=ProjectEvent.STATUS_OK, actor=self.owner)
        response = self.client_for(self.owner, 'pass-owner').get(
            f'/api/projects/{self.project.id}/events/',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['events'][0]['message'], 'Сайт опубликован.')
        self.assertEqual(response.data['events'][0]['kind'], 'publish')

    def test_outsider_does_not_see_events(self):
        record(self.project, ProjectEvent.KIND_BUILD, 'сборка')
        stranger = User.objects.create_user('stranger', password='pass-x')
        response = self.client_for(stranger, 'pass-x').get(
            f'/api/projects/{self.project.id}/events/',
        )
        self.assertEqual(response.status_code, 404)


class NotificationTests(EventBase):
    def test_event_goes_to_bound_chat(self):
        self.make_bot(chat_id=555)
        with mock.patch('telegram.notifications.send_message') as sender:
            record(self.project, ProjectEvent.KIND_PUBLISH,
                   'Сайт опубликован.', status=ProjectEvent.STATUS_OK,
                   actor=self.owner)
        sender.assert_called_once()
        token, chat_id, text = sender.call_args.args
        self.assertEqual(token, TOKEN)
        self.assertEqual(chat_id, 555)
        self.assertIn('Цветы', text)
        self.assertIn('Сайт опубликован.', text)
        self.assertIn('owner', text)

    def test_without_chat_nothing_is_sent(self):
        self.make_bot()
        with mock.patch('telegram.notifications.send_message') as sender:
            record(self.project, ProjectEvent.KIND_BUILD, 'сборка')
        sender.assert_not_called()

    def test_send_failure_is_swallowed(self):
        self.make_bot(chat_id=555)
        with mock.patch(
            'telegram.notifications.send_message',
            side_effect=BotApiError('bot was blocked by the user'),
        ):
            event = record(self.project, ProjectEvent.KIND_DEPLOY, 'деплой')
        self.assertIsNotNone(event)
        self.assertTrue(ProjectEvent.objects.filter(pk=event.pk).exists())

    def test_format_uses_plain_text(self):
        event = record(self.project, ProjectEvent.KIND_PUBLISH,
                       'Сайт https://shop_1.example опубликован.')
        text = format_event(event)
        # Подчёркивание в адресе ломало бы разметку markdown — поэтому
        # сообщение отправляется простым текстом.
        self.assertIn('shop_1.example', text)
        self.assertNotIn('*', text)
        self.assertIn('публикация', text)


class ChatBindingTests(EventBase):
    def bind(self, client, bot, payload=None, updates=None, error=None):
        with mock.patch('telegram.api.get_updates') as getter, \
                mock.patch('telegram.api.send_message') as sender:
            getter.return_value = updates or []
            if error is not None:
                getter.side_effect = error
            response = client.post(
                f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/chat/',
                payload or {}, format='json',
            )
        self.sender = sender
        return response

    def test_bind_finds_private_chat(self):
        bot = self.make_bot()
        client = self.client_for(self.owner, 'pass-owner')
        response = self.bind(client, bot, updates=[update(PRIVATE_CHAT)])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['notifyChatId'], 555)
        self.assertEqual(response.data['notifyChatTitle'], 'Иван Петров')
        self.assertTrue(response.data['notifyEnabled'])
        self.assertTrue(response.data['notified'])
        bot.refresh_from_db()
        self.assertEqual(bot.notify_chat_id, 555)
        self.sender.assert_called_once()

    def test_private_chat_wins_over_later_group(self):
        self.assertEqual(
            latest_chat([update(PRIVATE_CHAT, 1), update(GROUP_CHAT, 2)]),
            (555, 'Иван Петров'),
        )

    def test_group_is_used_when_no_private_chat(self):
        self.assertEqual(latest_chat([update(GROUP_CHAT)]), (-777, 'Рабочий чат'))

    def test_explicit_chat_id_is_accepted(self):
        bot = self.make_bot()
        response = self.bind(
            self.client_for(self.owner, 'pass-owner'), bot,
            payload={'chatId': 909, 'title': 'Стенд'},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['notifyChatId'], 909)
        self.assertEqual(response.data['notifyChatTitle'], 'Стенд')

    def test_no_messages_is_conflict(self):
        bot = self.make_bot()
        response = self.bind(self.client_for(self.owner, 'pass-owner'), bot)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'no_updates')
        bot.refresh_from_db()
        self.assertIsNone(bot.notify_chat_id)

    def test_telegram_error_is_reported(self):
        bot = self.make_bot()
        response = self.bind(
            self.client_for(self.owner, 'pass-owner'), bot,
            error=BotApiError('Telegram недоступен'),
        )
        self.assertEqual(response.status_code, 502)
        bot.refresh_from_db()
        self.assertIsNone(bot.notify_chat_id)

    def test_confirmation_failure_keeps_binding(self):
        bot = self.make_bot()
        client = self.client_for(self.owner, 'pass-owner')
        with mock.patch('telegram.api.get_updates',
                        return_value=[update(PRIVATE_CHAT)]), \
                mock.patch('telegram.api.send_message',
                           side_effect=BotApiError('blocked')):
            response = client.post(
                f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/chat/',
                {}, format='json',
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['notified'])
        bot.refresh_from_db()
        self.assertEqual(bot.notify_chat_id, 555)

    def test_bot_without_token_is_conflict(self):
        bot = TelegramBot(project=self.project, owner=self.owner,
                          name='Без токена', bot_username='no_token_bot')
        bot.save()
        response = self.bind(self.client_for(self.owner, 'pass-owner'), bot)
        self.assertEqual(response.status_code, 409)

    def test_unbind_clears_chat(self):
        bot = self.make_bot(chat_id=555)
        response = self.client_for(self.owner, 'pass-owner').delete(
            f'/api/projects/{self.project.id}/telegram-bot/{bot.id}/chat/',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['notifyEnabled'])
        bot.refresh_from_db()
        self.assertIsNone(bot.notify_chat_id)

    def test_editor_cannot_bind(self):
        bot = self.make_bot()
        editor = User.objects.create_user('editor', password='pass-ed')
        Membership.objects.create(project=self.project, user=editor, role=Role.EDITOR)
        response = self.bind(self.client_for(editor, 'pass-ed'), bot,
                             updates=[update(PRIVATE_CHAT)])
        self.assertEqual(response.status_code, 403)

    def test_outsider_gets_not_found(self):
        bot = self.make_bot()
        stranger = User.objects.create_user('stranger', password='pass-x')
        response = self.bind(self.client_for(stranger, 'pass-x'), bot)
        self.assertEqual(response.status_code, 404)


class BotApiPayloadTests(TestCase):
    def test_send_message_posts_chat_and_text(self):
        with mock.patch('telegram.bot_api.call') as caller:
            caller.return_value = {'message_id': 1}
            send_message(TOKEN, 555, 'привет')
        token, method, payload = caller.call_args.args
        self.assertEqual(token, TOKEN)
        self.assertEqual(method, 'sendMessage')
        self.assertEqual(payload['chat_id'], 555)
        self.assertEqual(payload['text'], 'привет')
        self.assertEqual(caller.call_args.kwargs['attempts'], 1)
