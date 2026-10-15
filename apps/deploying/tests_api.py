"""API профилей хостинга и деплоя (ТЗ п.16.5).

Проверяются вещи, из-за которых деплой опасен: чужой профиль не
достаётся, секрет не утекает, публиковать может не всякий, а сам
деплой не проходит под чужим ключом.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from projects.models import Project
from projects.versions import snapshot
from billing.models import Subscription
from secretstore.crypto import generate_key

#: Ключ шифрования для тестов: деплой хранит пароль, а пароль без
#: ключа платформа не хранит вовсе.
TEST_KEY = generate_key('test')


@override_settings(LOGIN_ATTEMPT_LIMIT=1000,
                   DJANGO_SECRET_ENCRYPTION_KEYS=TEST_KEY)
class ApiTestCase(TestCase):
    def setUp(self):
        # Троттлинг входа поднят: в тестах один адрес входит десятки
        # раз за минуту, иначе проверки упирались бы в антиперебор
        # (он проверяется отдельно, в LoginThrottleTests).
        cache.clear()
        User = get_user_model()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        Subscription.objects.create(user=self.owner, plan='start')
        self.editor = User.objects.create_user('editor', password='pass-editor')
        self.outsider = User.objects.create_user('outsider', password='pass-x')

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'site'
        self.root.mkdir(parents=True)

        self.project = Project.objects.create(
            owner=self.owner, name='Магазин',
            tree={'width': 1200, 'blocks': [{
                'id': 'b1', 'module': 'text.heading', 'x': 0, 'y': 0,
                'width': 600, 'height': 200, 'label': 'Блок',
                'props': {'text': 'Привет'},
            }]},
        )
        self.project.version += 1
        self.project.save(update_fields=['version'])
        snapshot(self.project, self.project.tree, author=self.owner, label='v1')

    def add_editor(self) -> None:
        from accounts.models import Membership

        Membership.objects.get_or_create(
            project=self.project, user=self.editor, defaults={'role': 'editor'}
        )

    def client_for(self, user, password: str) -> APIClient:
        client = APIClient()
        response = client.post(
            '/api/auth/login/',
            {'login': user.username, 'password': password},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}'
        )
        return client

    def create_profile(self, client, **overrides) -> dict:
        body = {
            'name': 'Мой хостинг',
            'kind': 'fs',
            'rootPath': str(self.root),
            'siteUrl': 'https://shop.example.ru',
        }
        body.update(overrides)
        return client.post(
            f'/api/projects/{self.project.id}/hosting/', body, format='json'
        )


class ProfileApiTests(ApiTestCase):
    def test_owner_creates_profile(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = self.create_profile(client)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['kind'], 'fs')
        self.assertFalse(response.data['hasSecret'])

    def test_secret_is_never_returned(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = self.create_profile(client, kind='ftp', host='ftp.example.ru',
                                       username='u', secret='пароль-123')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('пароль-123', json.dumps(response.data, ensure_ascii=False))

        listing = client.get(f'/api/projects/{self.project.id}/hosting/')
        self.assertNotIn('пароль-123', json.dumps(listing.data, ensure_ascii=False))

    def test_ftp_without_secret_is_rejected(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = self.create_profile(client, kind='ftp', host='ftp.example.ru',
                                       username='u')
        self.assertEqual(response.status_code, 400)
        self.assertIn('пароль', str(response.data['detail']).lower())

    def test_name_is_required(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = self.create_profile(client, name='  ')
        self.assertEqual(response.status_code, 400)

    def test_editor_cannot_add_access(self):
        """Участник проекта уйдёт из проекта вместе со своим доступом
        к чужому серверу."""
        self.add_editor()
        editor = self.client_for(self.editor, 'pass-editor')
        response = self.create_profile(editor, name='Профиль редактора')
        self.assertEqual(response.status_code, 403)

    def test_editor_can_read_profiles(self):
        """Список виден участнику: иначе непонятно, куда вообще
        публиковать."""
        client = self.client_for(self.owner, 'pass-owner')
        self.create_profile(client)
        self.add_editor()
        editor = self.client_for(self.editor, 'pass-editor')
        listing = editor.get(f'/api/projects/{self.project.id}/hosting/')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 1)

    def test_outsider_sees_nothing(self):
        client = self.client_for(self.outsider, 'pass-x')
        listing = client.get(f'/api/projects/{self.project.id}/hosting/')
        self.assertEqual(listing.status_code, 404)

    def test_empty_secret_keeps_previous(self):
        """Правка названия не должна обнулять пароль: иначе следующий
        деплой упал бы по невнятной причине."""
        client = self.client_for(self.owner, 'pass-owner')
        created = self.create_profile(client, kind='ftp', host='ftp.example.ru',
                                      username='u', secret='пароль-123')
        profile_id = created.data['id']

        response = client.patch(
            f'/api/projects/{self.project.id}/hosting/{profile_id}/',
            {'name': 'Переименованный'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['hasSecret'])

    def test_profile_can_be_deleted(self):
        client = self.client_for(self.owner, 'pass-owner')
        created = self.create_profile(client)
        response = client.delete(
            f'/api/projects/{self.project.id}/hosting/{created.data["id"]}/'
        )
        self.assertEqual(response.status_code, 204)
        listing = client.get(f'/api/projects/{self.project.id}/hosting/')
        self.assertEqual(listing.data, [])


class DeployApiTests(ApiTestCase):
    def profile_id(self, client) -> str:
        return self.create_profile(client).data['id']

    def test_owner_deploys(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = client.post(
            f'/api/projects/{self.project.id}/deploy/',
            {'profileId': self.profile_id(client), 'verify': False},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['ok'])
        self.assertGreater(response.data['filesUploaded'], 0)
        self.assertTrue((self.root / 'index.html').exists())

    def test_unknown_profile_is_404(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = client.post(
            f'/api/projects/{self.project.id}/deploy/',
            {'profileId': '999999'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_editor_cannot_deploy(self):
        """Деплой публикует сайт наружу: право такое же, как у выгрузки."""
        client = self.client_for(self.owner, 'pass-owner')
        profile_id = self.profile_id(client)
        self.add_editor()
        editor = self.client_for(self.editor, 'pass-editor')
        response = editor.post(
            f'/api/projects/{self.project.id}/deploy/',
            {'profileId': profile_id, 'verify': False}, format='json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.root / 'index.html').exists())

    def test_deploy_without_versions_is_409(self):
        client = self.client_for(self.owner, 'pass-owner')
        profile_id = self.profile_id(client)
        self.project.versions.all().delete()
        response = client.post(
            f'/api/projects/{self.project.id}/deploy/',
            {'profileId': profile_id, 'verify': False}, format='json',
        )
        self.assertEqual(response.status_code, 409)

    def test_deploy_writes_expected_package(self):
        """После деплоя сервер должен содержать ровно то, что открылось
        бы заказчику: тот же пакет, что и выгрузка."""
        client = self.client_for(self.owner, 'pass-owner')
        profile_id = self.profile_id(client)
        client.post(f'/api/projects/{self.project.id}/deploy/',
                    {'profileId': profile_id, 'verify': False}, format='json')

        html = (self.root / 'index.html').read_text(encoding='utf-8')
        self.assertIn('Привет', html)
        self.assertIn('AuraBuilder', html)
        self.assertTrue((self.root / 'build-manifest.json').exists())
        self.assertTrue((self.root / 'runtime.json').exists())
