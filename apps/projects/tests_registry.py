"""Тесты реестра модулей и эндпоинта каталога.

Реестр генерируется из docs/MODULE-CATALOG.md, поэтому тесты защищают
от двух типов расхождения: внутренней несогласованности (модуль без
категории, этап вне диапазона) и несовпадения с каталогом.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import default_tree
from projects.module_registry import (
    CATEGORIES,
    KINDS,
    MODULES,
    MODULE_IDS,
    modules_for_stage,
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
