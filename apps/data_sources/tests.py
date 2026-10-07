"""Узлы данных: источники, поля, записи и права.

Проверяется то, что нельзя увидеть на стенде, но сломает и 1С, и
экспорт: уникальность ключа источника, уникальность внешнего ключа
записи, типы значений и обязательные поля.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership, Role
from data_sources.models import DataRecord, DataSource, source_slug
from projects.models import Project, default_tree

User = get_user_model()

FIELDS = [
    {'key': 'title', 'label': 'Название', 'type': 'text', 'required': True},
    {'key': 'price', 'label': 'Цена', 'type': 'number', 'required': False},
]


class DataApiTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('tester', 'tester@example.com', 'verysecret123')
        self.project = Project.objects.create(
            name='Данные', tree=default_tree(), owner=self.user
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'tester', 'password': 'verysecret123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def create_source(self, name='Товары', fields=None, key=None):
        # key передаётся только когда он задан: пустая строка и null —
        # разные значения, а клиент без ключа не присылает поля вовсе.
        body = {'name': name, 'fields': FIELDS if fields is None else fields}
        if key is not None:
            body['key'] = key
        response = self.client.post(
            f'/api/projects/{self.project.id}/data/', body, format='json'
        )
        # id обязан быть только при успешном создании: часть тестов
        # проверяет отказ сервера, и требование id сломало бы их
        # раньше, чем дойдёт до сути.
        if response.status_code == status.HTTP_201_CREATED:
            self.assertIn('id', response.data, response.data)
        return response


class SourceTests(DataApiTestCase):
    def test_create_source(self):
        response = self.create_source()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['key'], 'tovary')
        self.assertEqual(response.data['recordCount'], 0)
        source = DataSource.objects.get(pk=response.data['id'])
        self.assertEqual(source.project_id, self.project.id)
        self.assertEqual(len(source.fields), 2)

    def test_key_is_unique_per_project(self):
        self.assertEqual(self.create_source(key='goods').status_code, 201)
        second = self.create_source(name='Другое', key='goods')
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('key', str(second.data))

    def test_same_key_in_another_project_allowed(self):
        other = Project.objects.create(
            name='Другой', tree=default_tree(), owner=self.user
        )
        self.create_source(key='goods')
        response = self.client.post(
            f'/api/projects/{other.id}/data/',
            {'name': 'Товары', 'key': 'goods', 'fields': FIELDS},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_field_keys_unique(self):
        response = self.create_source(
            fields=[
                {'key': 'title', 'label': 'А', 'type': 'text'},
                {'key': 'title', 'label': 'Б', 'type': 'text'},
            ]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_field_type_rejected(self):
        response = self.create_source(fields=[{'key': 'x', 'label': 'X', 'type': 'json'}])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_slug_from_cyrillic_name(self):
        # Название может быть русским, а ключ попадает в адрес
        # публикации и в экспорт: он должен оставаться латинским.
        response = self.create_source(name='Товары')
        self.assertEqual(response.data['key'], 'tovary')

    def test_cyrillic_field_key_rejected(self):
        # Клиент переводит кириллицу в ключе сам: подсказка в форме
        # показывает «nazvanie» сразу. Сервер остаётся строгим, потому
        # что ключ поля попадает в экспорт и в имена переменных, и
        # молча принять «название» значило бы разойтись с экспортом.
        response = self.create_source(
            fields=[{'key': 'название', 'label': 'Название', 'type': 'text'}]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_includes_record_count(self):
        source_id = self.create_source().data['id']
        self.client.post(
            f'/api/data/{source_id}/records/',
            {'data': {'title': 'Роза'}},
            format='json',
        )
        body = self.client.get(f'/api/projects/{self.project.id}/data/').json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['recordCount'], 1)

    def test_delete_source_removes_records(self):
        source_id = self.create_source().data['id']
        self.client.post(
            f'/api/data/{source_id}/records/',
            {'data': {'title': 'Роза'}},
            format='json',
        )
        response = self.client.delete(f'/api/data/{source_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(DataSource.objects.count(), 0)
        self.assertEqual(DataRecord.objects.count(), 0)


class RecordTests(DataApiTestCase):
    def setUp(self):
        super().setUp()
        self.source_id = self.create_source().data['id']

    def create_record(self, data=None, **extra):
        body = {'data': {'title': 'Роза'} if data is None else data}
        body.update(extra)
        return self.client.post(f'/api/data/{self.source_id}/records/', body, format='json')

    def test_create_record(self):
        response = self.create_record()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        record = DataRecord.objects.get(pk=response.data['id'])
        self.assertEqual(record.data['title'], 'Роза')
        self.assertEqual(record.position, 0)

    def test_positions_increment(self):
        first = self.create_record(data={'title': 'А'}).data['id']
        second = self.create_record(data={'title': 'Б'}).data['id']
        self.assertEqual(DataRecord.objects.get(pk=first).position, 0)
        self.assertEqual(DataRecord.objects.get(pk=second).position, 1)

    def test_required_field_missing(self):
        response = self.create_record(data={'price': 100})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', str(response.data))

    def test_unknown_field_rejected(self):
        response = self.create_record(data={'title': 'Роза', 'лишнее': 1})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('лишнее', str(response.data))

    def test_number_as_string_rejected(self):
        # Строковое число прошло бы незаметно и превратилось бы в
        # «100 ₽» в интерфейсе и в текст в экспорте.
        response = self.create_record(data={'title': 'Роза', 'price': '100'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('price', str(response.data))

    def test_boolean_type_checked(self):
        self.client.patch(
            f'/api/data/{self.source_id}/',
            {
                'fields': [
                    {'key': 'title', 'label': 'Название', 'type': 'text'},
                    {'key': 'hit', 'label': 'Хит', 'type': 'boolean'},
                ]
            },
            format='json',
        )
        response = self.create_record(data={'title': 'Роза', 'hit': 'да'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        ok = self.create_record(data={'title': 'Роза', 'hit': True})
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)

    def test_nested_value_rejected(self):
        response = self.create_record(data={'title': {'a': 1}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_external_id_unique(self):
        first = self.create_record(data={'title': 'А'}, externalId='abc')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.create_record(data={'title': 'Б'}, externalId='abc')
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('externalId', str(second.data))

    def test_records_without_external_id_allowed(self):
        # Внешний ключ есть только у данных, пришедших извне: свои
        # записи создаются без него, и их может быть сколько угодно.
        for title in ('А', 'Б', 'В'):
            response = self.create_record(data={'title': title})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_list_returns_total_and_limit(self):
        for i in range(5):
            self.create_record(data={'title': f'Товар {i}'})
        body = self.client.get(f'/api/data/{self.source_id}/records/').json()
        self.assertEqual(body['total'], 5)
        self.assertEqual(len(body['records']), 5)

        body = self.client.get(f'/api/data/{self.source_id}/records/?limit=2').json()
        self.assertEqual(len(body['records']), 2)
        self.assertEqual(body['total'], 5)

    def test_bad_limit_rejected(self):
        response = self.client.get(f'/api/data/{self.source_id}/records/?limit=abc')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_and_delete_record(self):
        record_id = self.create_record().data['id']
        response = self.client.patch(
            f'/api/data/records/{record_id}/',
            {'data': {'title': 'Изменено'}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(DataRecord.objects.get(pk=record_id).data['title'], 'Изменено')

        response = self.client.delete(f'/api/data/records/{record_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class DataAccessTests(DataApiTestCase):
    """Права на узлы данных (ТЗ п.11.1)."""

    def setUp(self):
        super().setUp()
        self.viewer = User.objects.create_user('viewer', 'v@example.com', 'verysecret123')
        Membership.objects.create(
            project=self.project, user=self.viewer, role=Role.VIEWER
        )
        self.outsider = User.objects.create_user('outsider', 'o@example.com', 'verysecret123')

    def _login(self, user):
        response = self.client.post(
            '/api/auth/login/',
            {'login': user.username, 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def test_viewer_cannot_create_source(self):
        self._login(self.viewer)
        response = self.client.post(
            f'/api/projects/{self.project.id}/data/',
            {'name': 'Товары', 'fields': FIELDS},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_can_read_records(self):
        # Viewer — «только просмотр черновика»: читать содержимое
        # узла данных он должен.
        source_id = self.create_source().data['id']
        self._login(self.viewer)
        response = self.client.get(f'/api/data/{source_id}/records/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_change_source_but_not_delete_it(self):
        # Редактор правит контент, но удаление источника уносит записи
        # и ломает блоки, которые на него ссылаются: по ТЗ п.11.1 это
        # делает владелец. Проверка держит границу между «можно
        # редактировать» и «можно уничтожить».
        editor = User.objects.create_user('editor', 'e@example.com', 'verysecret123')
        Membership.objects.create(project=self.project, user=editor, role=Role.EDITOR)
        source_id = self.create_source().data['id']

        self._login(editor)
        patched = self.client.patch(
            f'/api/data/{source_id}/', {'name': 'Товары сада'}, format='json'
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)

        deleted = self.client.delete(f'/api/data/{source_id}/')
        self.assertEqual(deleted.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(DataSource.objects.filter(pk=source_id).exists())

    def test_owner_deletes_source(self):
        # Владелец проекта остаётся Owner даже без записи в участниках:
        # удаление источника должно работать и в этом случае.
        self.project.owner = self.user
        self.project.save()
        source_id = self.create_source().data['id']
        response = self.client.delete(f'/api/data/{source_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_delete_record(self):
        # Запись — это контент, а не источник: редактор вправе её
        # убрать. Разница с источником проверяется выше.
        editor = User.objects.create_user('editor', 'e@example.com', 'verysecret123')
        Membership.objects.create(project=self.project, user=editor, role=Role.EDITOR)
        source_id = self.create_source().data['id']
        record_id = self.client.post(
            f'/api/data/{source_id}/records/',
            {'data': {'title': 'Роза'}},
            format='json',
        ).data['id']

        self._login(editor)
        response = self.client.delete(f'/api/data/records/{record_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(DataRecord.objects.count(), 0)

    def test_outsider_gets_404(self):
        self._login(self.outsider)
        response = self.client.get(f'/api/projects/{self.project.id}/data/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_rejected(self):
        self.client.credentials()
        response = self.client.get(f'/api/projects/{self.project.id}/data/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ModelTests(APITestCase):
    """Проверки, которые удобнее писать без HTTP."""

    def setUp(self):
        self.user = User.objects.create_user('u', 'u@example.com', 'verysecret123')
        self.project = Project.objects.create(
            name='П', tree=default_tree(), owner=self.user
        )
        self.source = DataSource.objects.create(
            project=self.project, name='Товары', key='goods', fields=FIELDS
        )

    def test_slug_helper(self):
        # slugify Django не переводит кириллицу, поэтому транслитерация
        # своя: без неё все русские названия давали ключ «source».
        self.assertEqual(source_slug('Цветы'), 'cvety')
        self.assertEqual(source_slug('   '), 'source')
        self.assertEqual(source_slug('Розы 2 шт'), 'rozy-2-sht')
        self.assertEqual(source_slug('Ёлка'), 'elka')
        self.assertEqual(source_slug('Товары и услуги'), 'tovary-i-uslugi')
        # Разные русские названия обязаны давать разные ключи.
        self.assertNotEqual(source_slug('Цветы'), source_slug('Ткани'))

    def test_external_id_constraint(self):
        from django.db import IntegrityError, transaction

        DataRecord.objects.create(
            source=self.source, external_id='1c-1', data={'title': 'А'}
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DataRecord.objects.create(
                    source=self.source, external_id='1c-1', data={'title': 'Б'}
                )

    def test_record_clean_reports_unknown_field(self):
        from django.core.exceptions import ValidationError

        record = DataRecord(source=self.source, data={'title': 'А', 'zzz': 1})
        with self.assertRaises(ValidationError):
            record.clean()

    def test_required_field_enforced_in_model(self):
        from django.core.exceptions import ValidationError

        record = DataRecord(source=self.source, data={})
        with self.assertRaises(ValidationError):
            record.clean()