"""Технические лимиты (ТЗ п.4.11).

Проверяется не только наличие значений, но и то, что превышение
действительно останавливает работу: лимит, который нигде не
применяется, выглядит как защита ровно до первого большого проекта.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from accounts.models import Membership, Role
from data_sources.models import DataRecord, DataSource
from projects.models import Project


def make_tree(count: int) -> dict:
    """Дерево из count модулей верхнего уровня."""
    return {
        'width': 720,
        'blocks': [
            {'id': f'b{i}', 'module': 'text.heading', 'x': 0, 'y': i * 40,
             'width': 640, 'height': 32, 'label': f'Блок {i}'}
            for i in range(count)
        ],
    }


class ModuleLimitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('limits', 'l@example.com', 'pw12345678')
        self.project = Project.objects.create(name='Пределы', owner=self.user, tree=make_tree(2))

    @override_settings(LIMITS={'MAX_MODULES_PER_PROJECT': 5})
    def test_tree_within_limit_is_valid(self):
        self.project.tree = make_tree(5)
        self.project.full_clean()  # ValidationError не поднимется

    @override_settings(LIMITS={'MAX_MODULES_PER_PROJECT': 5})
    def test_tree_over_limit_is_rejected(self):
        self.project.tree = make_tree(6)
        with self.assertRaises(ValidationError) as ctx:
            self.project.full_clean()
        self.assertIn('tree', ctx.exception.message_dict)

    @override_settings(LIMITS={'MAX_MODULES_PER_PROJECT': 5})
    def test_limit_message_shows_numbers(self):
        """Сообщение обязано называть факт и границу.

        Пользователь не может решить задачу по слову «слишком много»:
        ему нужно знать, сколько прибрать и до какого числа.
        """
        self.project.tree = make_tree(9)
        with self.assertRaises(ValidationError) as ctx:
            self.project.full_clean()
        text = str(ctx.exception.message_dict['tree'][0])
        self.assertIn('9', text)
        self.assertIn('5', text)

    def test_default_limits_are_sane(self):
        """Границы по умолчанию должны быть согласованы между собой.

        Лимит записей — это ещё и потолок размера выгрузки, поэтому
        он не может быть меньше лимита модулей в сотни раз: тогда
        проект упрётся в данные раньше, чем в содержимое.
        """
        from django.conf import settings

        self.assertLess(
            settings.LIMITS['MAX_MODULES_PER_PROJECT'],
            settings.LIMITS['MAX_RECORDS_PER_SOURCE'],
        )
        self.assertLessEqual(settings.LIMITS['MAX_MEMBERS_PER_PROJECT'], 100)


class RecordLimitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('recs', 'r@example.com', 'pw12345678')
        self.project = Project.objects.create(name='Записи', owner=self.user, tree=make_tree(1))
        self.source = DataSource.objects.create(
            project=self.project,
            name='Товары',
            key='tovari',
            fields=[{'key': 'title', 'label': 'Название', 'type': 'text', 'required': True}],
        )

    def _record(self, index: int) -> DataRecord:
        return DataRecord(
            source=self.source,
            data={'title': f'Запись {index}'},
            position=index,
        )

    @override_settings(LIMITS={'MAX_RECORDS_PER_SOURCE': 3})
    def test_records_up_to_limit_are_accepted(self):
        for i in range(3):
            self._record(i).full_clean()

    @override_settings(LIMITS={'MAX_RECORDS_PER_SOURCE': 3})
    def test_record_beyond_limit_is_rejected(self):
        for i in range(3):
            self._record(i).save()
        with self.assertRaises(ValidationError) as ctx:
            self._record(3).full_clean()
        self.assertIn('source', ctx.exception.message_dict)

    @override_settings(LIMITS={'MAX_RECORDS_PER_SOURCE': 3})
    def test_editing_existing_record_is_not_blocked(self):
        """Лимит считается при создании.

        Правка записи не увеличивает их число, и проверка на каждом
        сохранении отвергала бы редактирование последней записи при
        заполненном источнике.
        """
        existing = self._record(0)
        existing.save()
        existing.data = {'title': 'Изменено'}
        existing.full_clean()


class ExportRecordLimitTests(APITestCase):
    """Выгрузка не должна молча терять записи."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('exp', 'e@example.com', 'pw12345678')
        self.project = Project.objects.create(name='Выгрузка', owner=self.user, tree=make_tree(1))
        Membership.objects.create(project=self.project, user=self.user, role=Role.OWNER)
        self.source = DataSource.objects.create(
            project=self.project,
            name='Новости',
            key='novosti',
            fields=[{'key': 'title', 'label': 'Заголовок', 'type': 'text', 'required': True}],
        )
        # API ходит по JWT, а не по сессии: force_login здесь бесполезен
        # и даёт 401 вместо проверяемого ответа.
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'exp', 'password': 'pw12345678'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def _snapshot_with_source(self):
        self.project.tree = {
            'width': 720,
            'blocks': [{
                'id': 'b1', 'module': 'data.list', 'x': 0, 'y': 0,
                'width': 640, 'height': 200, 'label': 'Список',
                'props': {'source': str(self.source.id)},
            }],
        }
        self.project.save()
        return self.project.versions.create(number=1, tree=self.project.tree, author=self.user)

    @override_settings(LIMITS={'MAX_RECORDS_PER_SOURCE': 2})
    def test_export_over_limit_fails_loudly(self):
        for i in range(3):
            DataRecord.objects.create(source=self.source, data={'title': f'#{i}'}, position=i)
        self._snapshot_with_source()

        response = self.client.get(f'/api/projects/{self.project.id}/export/')

        # 413, а не 200 с неполным архивом: потеря данных обнаружилась
        # бы только на опубликованном сайте.
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['limit'], 'MAX_RECORDS_PER_SOURCE')

    @override_settings(LIMITS={'MAX_RECORDS_PER_SOURCE': 200})
    def test_export_keeps_every_record(self):
        """Раньше пакет содержал первые 100 записей и терял остальные.

        Записей больше ста, чтобы падение на срезе проявилось: лимит
        выше их числа, то есть выгрузка обязана пройти целиком.
        """
        for i in range(120):
            DataRecord.objects.create(source=self.source, data={'title': f'#{i}'}, position=i)
        self._snapshot_with_source()

        response = self.client.get(f'/api/projects/{self.project.id}/export/')
        self.assertEqual(response.status_code, 200)

        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            payload = zf.read('assets/data/data.json').decode('utf-8')
        self.assertIn('#119', payload)