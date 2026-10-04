"""Тесты реестра модулей и эндпоинта каталога.

Реестр генерируется из docs/MODULE-CATALOG.md, поэтому тесты защищают
от двух типов расхождения: внутренней несогласованности (модуль без
категории, этап вне диапазона) и несовпадения с каталогом.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Project, default_tree

User = get_user_model()
from projects.module_registry import (
    CATEGORIES,
    KINDS,
    MODULES,
    MODULE_IDS,
    SCHEMAS,
    SCHEMA_IDS,
    modules_for_stage,
    schema_for,
)
from projects.serializers import validate_tree


class RegistryIntegrityTests(APITestCase):
    """Целостность сгенерированного реестра."""

    def test_registry_matches_catalog_total(self):
        # docs/MODULE-CATALOG.md объявляет 65 модулей в трёх местах.
        self.assertEqual(len(MODULES), 65)
        self.assertEqual(len(MODULE_IDS), len(MODULES))

    def test_every_module_has_known_category(self):
        valid = {c['id'] for c in CATEGORIES}
        for module in MODULES:
            self.assertIn(module.category, valid, f'{module.id}: неизвестная категория')

    def test_every_module_has_known_kind(self):
        for module in MODULES:
            self.assertIn(module.kind, KINDS, f'{module.id}: неизвестный вид блока')

    def test_module_ids_are_unique(self):
        ids = [m.id for m in MODULES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_module_id_format(self):
        for module in MODULES:
            prefix, _, short = module.id.partition('.')
            self.assertTrue(prefix, f'{module.id}: нет префикса')
            self.assertTrue(short, f'{module.id}: нет имени')
            self.assertEqual(module.id, module.id.lower())

    def test_every_module_has_a_stage(self):
        for module in MODULES:
            self.assertTrue(module.stages, f'{module.id}: не указан этап')
            for stage in module.stages:
                self.assertIn(stage, (3, 5, 6), f'{module.id}: неожиданный этап {stage}')

    def test_min_stage_matches_stages(self):
        for module in MODULES:
            self.assertEqual(module.min_stage, min(module.stages))

    def test_every_module_has_label(self):
        for module in MODULES:
            self.assertTrue(module.name.strip(), f'{module.id}: пустое название')
            self.assertTrue(module.category_label.strip(), f'{module.id}: пустая категория')

    def test_stages_are_ascending(self):
        # Порядок этапов важен для фильтра: сортировка по minStage
        # предполагает, что список отсортирован.
        stages = [m.min_stage for m in MODULES]
        self.assertEqual(stages, sorted(stages), 'модули не отсортированы по этапу')

    def test_stage_filter_covers_everything(self):
        # Модуль, доступный на нескольких этапах, обязан попадать
        # в выборку каждого из них.
        for module in MODULES:
            for stage in module.stages:
                self.assertIn(module, modules_for_stage(stage))

    def test_default_tree_uses_registry_modules(self):
        # Стартовое дерево обязано состоять из реальных модулей,
        # иначе новый проект сразу станет невалидным.
        self.assertIsNone(validate_tree(default_tree()))
        for block in default_tree()['blocks']:
            self.assertIn(block['module'], MODULE_IDS)


class SchemaTests(APITestCase):
    """Схемы свойств: реестр, валидация и применение."""

    def _tree(self, module='section.hero', **block):
        base = {
            'id': 'a',
            'x': 0,
            'y': 0,
            'width': 640,
            'height': 200,
            'label': 'x',
            'module': module,
        }
        base.update(block)
        return {'width': 720, 'blocks': [base]}

    def test_three_schemas_defined(self):
        self.assertEqual(len(SCHEMAS), 3)
        self.assertEqual(SCHEMA_IDS, frozenset({'section.hero', 'text.heading', 'text.paragraph'}))

    def test_schema_props_have_types_from_allowed_set(self):
        from projects.serializers import ALLOWED_PROP_TYPES

        for schema in SCHEMAS.values():
            for prop in schema.props:
                self.assertIn(prop.type, ALLOWED_PROP_TYPES, f'{schema.module_id}.{prop.name}')

    def test_select_props_have_options(self):
        for schema in SCHEMAS.values():
            for prop in schema.props:
                if prop.type == 'select':
                    self.assertTrue(prop.limits.get('options'), f'{schema.module_id}.{prop.name}')

    def test_required_props_have_defaults(self):
        for schema in SCHEMAS.values():
            for prop in schema.props:
                if prop.required:
                    self.assertIsNotNone(prop.default, f'{schema.module_id}.{prop.name}')

    def test_defaults_only_contain_set_values(self):
        for schema in SCHEMAS.values():
            for name, value in schema.defaults().items():
                self.assertIsNotNone(value, f'{schema.module_id}.{name}')

    def test_schema_known_to_backend(self):
        self.assertIsNotNone(schema_for('section.hero'))
        self.assertIsNone(schema_for('section.header'))

    def test_accepts_valid_props(self):
        from projects.serializers import validate_tree

        self.assertIsNone(
            validate_tree(self._tree(props={'background': 'accent', 'size': 'fullscreen'}))
        )

    def test_rejects_unknown_prop(self):
        from projects.serializers import validate_tree

        error = validate_tree(self._tree(props={'нетакого': 'x'}))
        self.assertIsNotNone(error)
        self.assertIn('не описано', error)

    def test_rejects_bad_select_value(self):
        from projects.serializers import validate_tree

        error = validate_tree(self._tree(props={'background': 'розовый'}))
        self.assertIsNotNone(error)
        self.assertIn('background', error)

    def test_rejects_prop_for_module_without_schema(self):
        # У section.header схемы нет: принимаются только скаляры,
        # иначе в базу попадёт вложенность, которую экспорт не разберёт.
        from projects.serializers import validate_tree

        tree = self._tree(module='section.header', props={'любое': 'значение'})
        self.assertIsNone(validate_tree(tree))

        nested = self._tree(module='section.header', props={'любое': {'a': 1}})
        self.assertIsNotNone(validate_tree(nested))

    def test_rejects_too_many_props(self):
        from projects.serializers import MAX_PROPS, validate_tree

        tree = self._tree(props={f'p{i}': 'x' for i in range(MAX_PROPS + 1)})
        self.assertIsNotNone(validate_tree(tree))

    def test_number_prop_bounds(self):
        from projects.serializers import validate_tree

        # maxWidth у text.paragraph ограничен 240–960.
        self.assertIsNone(validate_tree(self._tree(module='text.paragraph', props={'maxWidth': 480})))
        self.assertIsNotNone(validate_tree(self._tree(module='text.paragraph', props={'maxWidth': 10})))
        self.assertIsNotNone(validate_tree(self._tree(module='text.paragraph', props={'maxWidth': 5000})))

    def test_number_prop_rejects_string(self):
        from projects.serializers import validate_tree

        error = validate_tree(self._tree(module='text.paragraph', props={'maxWidth': 'много'}))
        self.assertIsNotNone(error)
        self.assertIn('maxWidth', error)

    def test_long_text_prop_rejected(self):
        from projects.serializers import validate_tree

        error = validate_tree(self._tree(props={'heading': 'я' * 500}))
        self.assertIsNotNone(error)
        self.assertIn('heading', error)


class SchemaPropsRoundTripTests(APITestCase):
    """Свойства доходят до базы и обратно, а мусор не проходит.

    Отдельная проверка validate_tree тут не годится: панель пишет props
    через API, и ошибка может прятаться в сериализаторе, в преобразовании
    имён полей или в самой записи в jsonb.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('tester', 'tester@example.com', 'verysecret123')
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'tester', 'password': 'verysecret123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def _save(self, props):
        project = Project.objects.create(
            name='Проверка props', tree=default_tree(), owner=self.user
        )
        response = self.client.put(
            f'/api/projects/{project.pk}/',
            {
                'name': 'Проверка props',
                'tree': {
                    'width': 720,
                    'blocks': [
                        {
                            'id': 'hero',
                            'module': 'section.hero',
                            'x': 40,
                            'y': 40,
                            'width': 640,
                            'height': 200,
                            'label': 'Первый экран',
                            'props': props,
                        }
                    ],
                },
            },
            format='json',
        )
        return project, response

    def test_valid_props_are_stored_and_returned(self):
        props = {'heading': 'Заголовок', 'background': 'accent', 'size': 'fullscreen'}
        project, response = self._save(props)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        project.refresh_from_db()
        stored = project.tree['blocks'][0]['props']
        self.assertEqual(stored['heading'], 'Заголовок')
        self.assertEqual(stored['background'], 'accent')

        # Сервер отдаёт дерево в том же виде, в каком его читает редактор.
        again = self.client.get(f'/api/projects/{project.pk}/')
        self.assertEqual(again.json()['tree']['blocks'][0]['props']['heading'], 'Заголовок')

    def test_number_prop_stays_number(self):
        # Строкой число прошло бы незаметно для интерфейса, но
        # отрендерилось бы как «480px» в поле и уехало в экспорт строкой.
        project, response = self._save({'heading': 'Проверка числа'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f'/api/projects/{project.pk}/',
            {
                'tree': {
                    'width': 720,
                    'blocks': [
                        {
                            'id': 'text',
                            'module': 'text.paragraph',
                            'x': 0,
                            'y': 0,
                            'width': 320,
                            'height': 80,
                            'label': 'Текст',
                            'props': {'maxWidth': 480},
                        }
                    ],
                }
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        project.refresh_from_db()
        self.assertEqual(project.tree['blocks'][0]['props']['maxWidth'], 480)

    def test_invalid_props_rejected_with_reason(self):
        project, response = self._save({'background': 'розовый'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Причина нужна в ответе: панель показывает её пользователю.
        self.assertIn('background', str(response.data))

    def test_props_survive_round_trip_with_label(self):
        # Свойства и название правятся одной панелью: одно поле не
        # должно затирать остальные.
        project, response = self._save({'heading': 'Первый'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f'/api/projects/{project.pk}/',
            {
                'tree': {
                    'width': 720,
                    'blocks': [
                        {
                            'id': 'hero',
                            'module': 'section.hero',
                            'x': 40,
                            'y': 40,
                            'width': 640,
                            'height': 200,
                            'label': 'Переименован',
                            'props': {'heading': 'Первый'},
                        }
                    ],
                }
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        project.refresh_from_db()
        block = project.tree['blocks'][0]
        self.assertEqual(block['label'], 'Переименован')
        self.assertEqual(block['props']['heading'], 'Первый')


class ModuleCatalogApiTests(APITestCase):
    """Эндпоинт GET /api/modules/."""

    def test_returns_full_registry(self):
        response = self.client.get('/api/modules/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body['total'], 65)
        self.assertEqual(len(body['modules']), 65)
        self.assertEqual(len(body['categories']), 5)

    def test_module_payload_shape(self):
        body = self.client.get('/api/modules/').json()
        module = body['modules'][0]
        for key in ('id', 'name', 'category', 'categoryLabel', 'kind', 'stages', 'minStage'):
            self.assertIn(key, module)
        self.assertIsInstance(module['stages'], list)
        self.assertIsInstance(module['minStage'], int)

    def test_filter_by_stage(self):
        response = self.client.get('/api/modules/?stage=3')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body['total'], len(body['modules']))
        for module in body['modules']:
            self.assertIn(3, module['stages'])

    def test_filter_by_stage_and_category(self):
        body = self.client.get('/api/modules/?stage=3&category=structure').json()
        for module in body['modules']:
            self.assertEqual(module['category'], 'structure')
            self.assertIn(3, module['stages'])

    def test_invalid_stage_rejected(self):
        response = self.client.get('/api/modules/?stage=abc')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_category_returns_empty(self):
        body = self.client.get('/api/modules/?category=нетакой').json()
        self.assertEqual(body['total'], 0)

    def test_stage_filter_is_subset_of_full(self):
        all_ids = {m['id'] for m in self.client.get('/api/modules/').json()['modules']}
        stage_ids = {m['id'] for m in self.client.get('/api/modules/?stage=3').json()['modules']}
        self.assertTrue(stage_ids.issubset(all_ids))
        self.assertTrue(stage_ids)  # не пусто
