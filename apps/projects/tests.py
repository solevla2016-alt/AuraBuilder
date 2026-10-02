"""Тесты вертикального среза: сохранение и загрузка дерева страницы.

Проверяется ровно то, ради чего срез делался: данные доходят до базы
и возвращаются без потерь, а невалидное дерево отвергается сервером.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Project, default_tree
from projects.serializers import validate_tree


class ValidateTreeTests(APITestCase):
    """Проверка дерева на сервере — браузеру доверять нельзя."""

    def test_default_tree_is_valid(self):
        self.assertIsNone(validate_tree(default_tree()))

    def test_rejects_non_object(self):
        self.assertIsNotNone(validate_tree('строка'))
        self.assertIsNotNone(validate_tree(None))

    def test_rejects_missing_blocks(self):
        self.assertIsNotNone(validate_tree({'width': 720}))

    def test_rejects_zero_width_page(self):
        self.assertIsNotNone(validate_tree({'width': 0, 'blocks': []}))

    def test_rejects_negative_block_size(self):
        tree = {'width': 720, 'blocks': [
            {'id': 'a', 'x': 0, 'y': 0, 'width': -10, 'height': 20,
             'module': 'text.paragraph', 'label': 'x'},
        ]}
        self.assertIsNotNone(validate_tree(tree))

    def test_rejects_duplicate_ids(self):
        tree = {'width': 720, 'blocks': [
            {'id': 'a', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
             'module': 'text.paragraph', 'label': 'x'},
            {'id': 'a', 'x': 5, 'y': 5, 'width': 10, 'height': 20,
             'module': 'text.paragraph', 'label': 'y'},
        ]}
        error = validate_tree(tree)
        self.assertIsNotNone(error)
        self.assertIn('повторяющийся', error)

    def test_rejects_unknown_module(self):
        # Модуль сверяется с реестром: неизвестный id в базу попасть не
        # может, иначе экспорт (ТЗ п.16.2) не найдёт для него блок.
        tree = {'width': 720, 'blocks': [
            {'id': 'a', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
             'module': 'нетакого.модуля', 'label': 'x'},
        ]}
        error = validate_tree(tree)
        self.assertIsNotNone(error)
        self.assertIn('неизвестный модуль', error)

    def test_rejects_missing_module(self):
        tree = {'width': 720, 'blocks': [
            {'id': 'a', 'x': 0, 'y': 0, 'width': 10, 'height': 20, 'label': 'x'},
        ]}
        self.assertIsNotNone(validate_tree(tree))

    def test_rejects_kind_instead_of_module(self):
        # Старое поле kind больше не принимается: оно описывало заливку
        # холста, а не модуль каталога.
        tree = {'width': 720, 'blocks': [
            {'id': 'a', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
             'kind': 'text', 'label': 'x'},
        ]}
        self.assertIsNotNone(validate_tree(tree))

    def test_accepts_every_registry_module(self):
        # Каждый модуль реестра должен приниматься валидатором: иначе
        # палитра покажет модуль, который невозможно положить на холст.
        from .module_registry import MODULES

        tree = {
            'width': 720,
            'blocks': [
                {'id': f'b{i}', 'module': m.id, 'x': 0, 'y': 0,
                 'width': 100, 'height': 40, 'label': m.name}
                for i, m in enumerate(MODULES)
            ],
        }
        self.assertIsNone(validate_tree(tree))

    def test_rejects_nan_and_infinity(self):
        # float('nan') проходит isinstance(x, float), но ломает JSON-экспорт
        tree = {'width': 720, 'blocks': [
            {'id': 'a', 'x': float('nan'), 'y': 0, 'width': 10, 'height': 20,
             'module': 'text.paragraph', 'label': 'x'},
        ]}
        self.assertIsNotNone(validate_tree(tree))

    def test_rejects_boolean_as_number(self):
        # True — экземпляр int в Python; такое значение не должно проходить
        tree = {'width': 720, 'blocks': [
            {'id': 'a', 'x': True, 'y': 0, 'width': 10, 'height': 20,
             'module': 'text.paragraph', 'label': 'x'},
        ]}
        self.assertIsNotNone(validate_tree(tree))

    def test_rejects_too_many_blocks(self):
        blocks = [
            {'id': f'b{i}', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
             'module': 'text.paragraph', 'label': 'x'}
            for i in range(501)
        ]
        self.assertIsNotNone(validate_tree({'width': 720, 'blocks': blocks}))

    def test_accepts_empty_blocks(self):
        self.assertIsNone(validate_tree({'width': 720, 'blocks': []}))


class ProjectApiTests(APITestCase):
    """Создание, чтение и сохранение проекта через API."""

    def test_health(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'ok')

    def test_create_project_gets_default_tree(self):
        response = self.client.post('/api/projects/', {'name': 'Тест'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        body = response.json()
        self.assertEqual(body['name'], 'Тест')
        self.assertEqual(body['tree'], default_tree())
        self.assertTrue(Project.objects.filter(pk=body['id']).exists())

    def test_get_missing_project_returns_404(self):
        response = self.client.get('/api/projects/00000000-0000-4000-8000-000000000099/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_uuid_returns_400(self):
        response = self.client.get('/api/projects/не-uuid/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_save_tree_roundtrip(self):
        project = Project.objects.create(name='Проект')

        new_tree = {
            'width': 900,
            'blocks': [
                {'id': 'hero', 'x': 12, 'y': 34, 'width': 800, 'height': 300,
                 'module': 'section.hero', 'label': 'Первый экран'},
                {'id': 'txt', 'x': 12, 'y': 400, 'width': 400, 'height': 90,
                 'module': 'text.paragraph', 'label': 'Акция'},
            ],
        }
        response = self.client.put(
            f'/api/projects/{project.pk}/',
            {'name': 'Проект', 'tree': new_tree},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['tree'], new_tree)

        # Повторное чтение из БД: данные не потерялись по пути
        response = self.client.get(f'/api/projects/{project.pk}/')
        self.assertEqual(response.json()['tree'], new_tree)

        project.refresh_from_db()
        self.assertEqual(project.tree, new_tree)

    def test_save_rejects_invalid_tree(self):
        project = Project.objects.create(name='Проект')
        response = self.client.put(
            f'/api/projects/{project.pk}/',
            {'name': 'Проект', 'tree': {'width': 720, 'blocks': [{'id': 'x'}]}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Невалидное дерево не должно записаться в базу
        project.refresh_from_db()
        self.assertEqual(project.tree, default_tree())

    def test_partial_update_changes_only_name(self):
        project = Project.objects.create(name='Старое')
        response = self.client.patch(
            f'/api/projects/{project.pk}/', {'name': 'Новое'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['name'], 'Новое')
        self.assertEqual(response.json()['tree'], default_tree())

    def test_blank_name_rejected(self):
        response = self.client.post('/api/projects/', {'name': '   '}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_returns_projects(self):
        Project.objects.create(name='Первый')
        Project.objects.create(name='Второй')
        response = self.client.get('/api/projects/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 2)

    def test_delete_project(self):
        project = Project.objects.create(name='Проект')
        response = self.client.delete(f'/api/projects/{project.pk}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())

    def test_create_with_fixed_id_is_idempotent(self):
        # Редактор при первом запуске инициализирует стендовый проект
        # с постоянным UUID: второй вызов не должен создавать дубль.
        fixed_id = '00000000-0000-4000-8000-000000000001'
        payload = {'id': fixed_id, 'name': 'Стенд', 'tree': default_tree()}

        first = self.client.post('/api/projects/', payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.json()['id'], fixed_id)

        second = self.client.post('/api/projects/', payload, format='json')
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(Project.objects.count(), 1)

    def test_response_uses_camel_case_dates(self):
        # Клиент читает createdAt/updatedAt (apps/web/src/ui/project.ts).
        # Сервер отдаёт snake_case — редактор получал бы undefined.
        project = Project.objects.create(name='Проект')
        body = self.client.get(f'/api/projects/{project.pk}/').json()
        self.assertIn('updatedAt', body)
        self.assertIn('createdAt', body)
        self.assertNotIn('updated_at', body)

    def test_updated_at_changes_on_save(self):
        project = Project.objects.create(name='Проект')
        first = project.updated_at
        self.client.put(
            f'/api/projects/{project.pk}/',
            {'name': 'Переименован', 'tree': default_tree()},
            format='json',
        )
        project.refresh_from_db()
        self.assertNotEqual(project.updated_at, first)
