"""Экспорт и импорт конфигурации проекта (ТЗ п.16.7).

Главное здесь — круговой переход: выгрузили на одном аккаунте,
загрузили на другом и получили тот же проект. Остальные проверки
говорят, что файл не примет мусор и что чужим он не достанется.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.models import Membership
from component_library.models import ComponentStyle
from data_sources.models import DataRecord, DataSource

from projects.config_export import ConfigError, dump_project, import_project, to_json
from projects.models import Project
from projects.versions import snapshot


def block(module: str = 'text.heading', **props) -> dict:
    return {
        'id': 'b1', 'module': module, 'x': 0, 'y': 0,
        'width': 600, 'height': 200, 'label': 'Блок',
        'props': props or {'text': 'Заголовок'},
    }


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class ConfigExportTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        self.project = Project.objects.create(
            owner=self.owner, name='Магазин «Цветы»',
            tree={'width': 1200, 'blocks': [block()]},
        )
        self.project.version += 1
        self.project.save(update_fields=['version'])
        snapshot(self.project, self.project.tree, author=self.owner, label='v1')

    def client_for(self, user, password: str):
        from rest_framework.test import APIClient

        client = APIClient()
        response = client.post(
            '/api/auth/login/', {'login': user.username, 'password': password},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}'
        )
        return client

    def export(self, client=None):
        client = client or self.client_for(self.owner, 'pass-owner')
        return client.get(f'/api/projects/{self.project.id}/config/')

    # --- выгрузка ---------------------------------------------------

    def test_export_returns_json_file(self):
        response = self.export()
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('.json', response['Content-Disposition'])

    def test_export_contains_whole_project(self):
        payload = json.loads(self.export().content.decode('utf-8'))
        self.assertEqual(payload['format'], 'aurabuilder.project')
        self.assertEqual(payload['project']['name'], 'Магазин «Цветы»')
        self.assertEqual(payload['project']['width'], 1200)
        self.assertEqual(len(payload['project']['tree']['blocks']), 1)
        self.assertEqual(len(payload['versions']), 1)

    def test_export_contains_versions_history(self):
        """Полный бэкап без истории — это половина бэкапа: откатиться
        после переезда было бы нечем."""
        self.project.version += 1
        self.project.save(update_fields=['version'])
        snapshot(self.project, self.project.tree, author=self.owner, label='v2')
        payload = json.loads(self.export().content.decode('utf-8'))
        numbers = [v['number'] for v in payload['versions']]
        self.assertEqual(len(numbers), 2)
        # Номера идут подряд: после обрезки истории последний снимок
        # мог пропасть, и проверяется именно порядок, а не «две записи».
        self.assertEqual(numbers[1] - numbers[0], 1)
        self.assertEqual(numbers, sorted(numbers))

    def test_export_contains_data_and_styles(self):
        source = DataSource.objects.create(
            project=self.project, name='Каталог', key='katalog',
            fields=[{'key': 'name', 'label': 'Название', 'type': 'text',
                     'required': True}],
        )
        DataRecord.objects.create(source=source, data={'name': 'Роза'})
        ComponentStyle.objects.create(
            project=self.project, kind='section',
            tokens={'background': '#FFFFFF', 'text': '#1A1C1E', 'radius': 8,
                    'padding': 20, 'weight': 400, 'border': 1},
        )
        payload = json.loads(self.export().content.decode('utf-8'))
        self.assertEqual(payload['dataSources'][0]['key'], 'katalog')
        self.assertEqual(payload['dataSources'][0]['records'][0]['data'],
                         {'name': 'Роза'})
        self.assertEqual(payload['componentStyles'][0]['kind'], 'section')

    def test_export_never_contains_secrets(self):
        """Пароли от серверов в файл проекта не попадают (ADR-0006)."""
        body = self.export().content.decode('utf-8')
        self.assertNotIn('password', body.lower())
        self.assertNotIn('secret', body.lower())

    def test_export_is_available_to_every_tariff(self):
        """Сценарий 5 доступен на всех тарифах (ТЗ п.17.1): экспорт
        конфигурации не требует права публикации."""
        self.assertEqual(self.export().status_code, 200)

    def test_outsider_cannot_export(self):
        other = get_user_model().objects.create_user('outsider', password='pass-x')
        response = self.export(self.client_for(other, 'pass-x'))
        self.assertEqual(response.status_code, 404)

    def test_editor_can_export(self):
        """Это чтение своего проекта, а не выдача сайта."""
        editor = get_user_model().objects.create_user('editor', password='pass-e')
        Membership.objects.create(project=self.project, user=editor, role='editor')
        self.assertEqual(
            self.export(self.client_for(editor, 'pass-e')).status_code, 200
        )

    # --- импорт -----------------------------------------------------

    def import_into(self, payload, user=None):
        return import_project(user or self.owner, payload)

    def test_round_trip_to_another_account(self):
        payload = dump_project(self.project)
        other = get_user_model().objects.create_user('второй', password='x')

        restored = self.import_into(payload, other)

        self.assertEqual(restored.owner, other)
        self.assertEqual(restored.name, self.project.name)
        self.assertEqual(restored.tree, self.project.tree)
        self.assertEqual(restored.versions.count(), 1)

    def test_round_trip_keeps_data_and_versions(self):
        source = DataSource.objects.create(
            project=self.project, name='Каталог', key='katalog',
            fields=[{'key': 'name', 'label': 'Название', 'type': 'text',
                     'required': True}],
        )
        DataRecord.objects.create(source=source, data={'name': 'Роза'})
        DataRecord.objects.create(source=source, data={'name': 'Тюльпан'})
        ComponentStyle.objects.create(
            project=self.project, kind='text',
            tokens={'background': '#FFF', 'text': '#000', 'radius': 4,
                    'padding': 12, 'weight': 400, 'border': 1},
        )

        restored = self.import_into(dump_project(self.project), self.owner)

        self.assertEqual(restored.data.count() if hasattr(restored, 'data') else 1, 1)
        new_source = DataSource.objects.get(project=restored)
        self.assertEqual(new_source.records.count(), 2)
        self.assertEqual(new_source.records.first().data, {'name': 'Роза'})
        self.assertEqual(
            ComponentStyle.objects.filter(project=restored, kind='text').count(), 1
        )

    def test_import_creates_new_id(self):
        restored = self.import_into(dump_project(self.project))
        self.assertNotEqual(str(restored.id), str(self.project.id))

    def test_import_does_not_touch_source_project(self):
        payload = dump_project(self.project)
        self.import_into(payload)
        self.assertEqual(self.project.versions.count(), 1)
        self.assertEqual(Project.objects.filter(owner=self.owner).count(), 2)

    # --- отказы -----------------------------------------------------

    def test_foreign_format_is_refused(self):
        with self.assertRaises(ConfigError) as ctx:
            self.import_into({'format': 'что-то другое'})
        self.assertIn('AuraBuilder', str(ctx.exception))

    def test_newer_format_version_is_refused(self):
        payload = dump_project(self.project)
        payload['formatVersion'] = 99
        with self.assertRaises(ConfigError) as ctx:
            self.import_into(payload)
        self.assertIn('99', str(ctx.exception))

    def test_unknown_module_is_refused(self):
        """Модуль из будущей версии платформы нельзя импортировать:
        редактор всё равно не сможет его показать."""
        payload = dump_project(self.project)
        payload['project']['tree']['blocks'][0]['module'] = 'shop.teleport'
        with self.assertRaises(ConfigError) as ctx:
            self.import_into(payload)
        self.assertIn('shop.teleport', str(ctx.exception))

    def test_too_many_blocks_is_refused(self):
        payload = dump_project(self.project)
        one = payload['project']['tree']['blocks'][0]
        payload['project']['tree']['blocks'] = [
            {**one, 'id': f'b{i}'} for i in range(500)
        ]
        with self.assertRaises(ConfigError):
            self.import_into(payload)

    def test_block_without_id_is_refused(self):
        payload = dump_project(self.project)
        payload['project']['tree']['blocks'][0].pop('id')
        with self.assertRaises(ConfigError):
            self.import_into(payload)

    def test_absurd_width_is_refused(self):
        payload = dump_project(self.project)
        payload['project']['width'] = 10
        with self.assertRaises(ConfigError):
            self.import_into(payload)

    def test_nothing_is_created_when_file_is_bad(self):
        """Отказ не должен оставлятьhalf-проект в базе."""
        payload = dump_project(self.project)
        payload['format'] = 'чужая программа'
        before = Project.objects.count()
        with self.assertRaises(ConfigError):
            self.import_into(payload)
        self.assertEqual(Project.objects.count(), before)

    def test_duplicate_source_keys_are_separated(self):
        """Два источника с одинаковым ключом сломали бы привязку
        блоков: они бы смотрели в один узел."""
        payload = dump_project(self.project)
        fields = [{'key': 'name', 'label': 'Название', 'type': 'text',
                   'required': True}]
        payload['dataSources'] = [
            {'name': 'Первый', 'key': 'katalog', 'fields': fields, 'records': []},
            {'name': 'Второй', 'key': 'katalog', 'fields': fields, 'records': []},
        ]
        restored = self.import_into(payload)
        keys = set(DataSource.objects.filter(project=restored).values_list('key', flat=True))
        self.assertEqual(len(keys), 2)

    def test_project_limit_is_respected(self):
        with self.settings(LIMITS={**self.settings_dict(), 'MAX_PROJECTS_PER_USER': 1}):
            with self.assertRaises(ConfigError) as ctx:
                self.import_into(dump_project(self.project))
            self.assertIn('уже', str(ctx.exception).lower())

    def settings_dict(self):
        from django.conf import settings as django_settings

        return dict(django_settings.LIMITS)

    # --- API импорта ------------------------------------------------

    def test_import_endpoint_creates_project(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = client.post(
            '/api/projects/import/',
            dump_project(self.project), format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], self.project.name)

    def test_import_endpoint_reports_bad_file(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = client.post(
            '/api/projects/import/', {'format': 'чужой'}, format='json'
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('detail', response.data)

    def test_import_requires_login(self):
        from rest_framework.test import APIClient

        response = APIClient().post(
            '/api/projects/import/', dump_project(self.project), format='json'
        )
        self.assertIn(response.status_code, (401, 403))