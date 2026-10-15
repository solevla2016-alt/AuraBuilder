"""Логика в сборке пакета и в API (ТЗ п.6.4).

Сквозная проверка: граф в документе проекта попадает в пакет,
компилируется и виден в манифесте сборки.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from billing.models import Subscription
from projects.models import DocumentVersion, Project, default_tree
from projects.package import build_package
from projects.versions import snapshot

from .graph import LOGIC_KEY

User = get_user_model()

GRAPH = {
    'nodes': [
        {'id': 'n1', 'type': 'trigger.click', 'props': {'blockId': 'b1'}},
        {'id': 'n2', 'type': 'condition.property',
         'props': {'source': 'data.cart.count', 'operator': 'gt',
                   'value': '0'}},
        {'id': 'n3', 'type': 'action.message',
         'props': {'text': 'Спасибо за заказ', 'tone': 'success'}},
    ],
    'edges': [
        {'source': 'n1', 'target': 'n2', 'branch': ''},
        {'source': 'n2', 'target': 'n3', 'branch': 'yes'},
    ],
}


def block(module: str = 'text.heading', **props) -> dict:
    return {
        'id': 'b1', 'module': module, 'x': 0, 'y': 0, 'width': 600,
        'height': 200, 'props': {'text': 'Заголовок', **props},
    }


class LogicPackageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        Subscription.objects.create(user=self.owner, plan='pro')
        self.project = Project.objects.create(owner=self.owner,
                                              name='Магазин')

    def build(self, graph=None, version: DocumentVersion | None = None):
        tree = dict(default_tree())
        tree['blocks'] = [block()]
        if graph is not None:
            tree[LOGIC_KEY] = graph
        if version is None:
            version = snapshot(self.project, tree, author=self.owner,
                               label='v1')
        return build_package(self.project, version)

    def test_logic_file_is_always_present(self):
        built = self.build()
        self.assertIn('assets/js/logic.js', built['files'])
        self.assertIn('Граф пуст', built['files']['assets/js/logic.js'])

    def test_script_is_linked_from_page(self):
        built = self.build(GRAPH)
        self.assertIn('assets/js/logic.js', built['files']['index.html'])
        self.assertIn('Спасибо за заказ', built['files']['assets/js/logic.js'])

    def test_declaration_goes_with_script(self):
        built = self.build(GRAPH)
        declaration = json.loads(built['files']['logic.json'])
        self.assertEqual(len(declaration['nodes']), 3)
        self.assertEqual(declaration['triggers'], ['n1'])

    def test_declaration_absent_for_empty_graph(self):
        built = self.build()
        self.assertNotIn('logic.json', built['files'])

    def test_manifest_reports_logic(self):
        manifest = self.build(GRAPH)['manifest']
        self.assertEqual(manifest['logic']['nodes'], 3)
        self.assertEqual(manifest['logic']['actions'], 1)
        self.assertFalse(manifest['logic']['requiresRuntime'])

    def test_server_node_marks_runtime_needed(self):
        graph = json.loads(json.dumps(GRAPH))
        graph['nodes'][2] = {'id': 'n3', 'type': 'action.submit',
                             'props': {'blockId': 'b1'}}
        manifest = self.build(graph)['manifest']
        self.assertTrue(manifest['logic']['requiresRuntime'])

    def test_broken_graph_stops_the_build(self):
        graph = json.loads(json.dumps(GRAPH))
        graph['edges'].append({'source': 'n3', 'target': 'n1',
                               'branch': ''})
        with self.assertRaises(Exception) as ctx:
            self.build(graph)
        self.assertIn('нет продолжения', str(ctx.exception))

    def test_package_has_no_external_dependencies(self):
        built = self.build(GRAPH)
        for name, content in built['files'].items():
            if name.endswith('.js'):
                self.assertNotIn('http://', content)
                self.assertNotIn('https://', content)

LOGIN_URL = '/api/auth/login/'


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class LogicApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        Subscription.objects.create(user=self.owner, plan='pro')
        self.editor = User.objects.create_user('editor', password='pass-ed')
        self.project = Project.objects.create(owner=self.owner,
                                              name='Магазин')
        self.client = APIClient()

    def login(self, username='owner', password='pass-owner'):
        response = self.client.post(LOGIN_URL, {'login': username,
                                                'password': password},
                                    format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + response.data['access'])

    def test_library_lists_types(self):
        self.login()
        response = self.client.get('/api/logic/types/')
        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data['types']}
        self.assertIn('trigger.click', ids)
        self.assertIn('action.message', ids)

    def test_empty_graph_is_reported_as_empty(self):
        self.login()
        response = self.client.get(f'/api/projects/{self.project.id}/logic/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['empty'])
        self.assertTrue(response.data['valid'])

    def test_graph_is_returned_with_stats(self):
        tree = dict(default_tree())
        tree[LOGIC_KEY] = GRAPH
        self.project.tree = tree
        self.project.save()
        self.login()
        response = self.client.get(f'/api/projects/{self.project.id}/logic/')
        self.assertEqual(response.data['stats']['nodes'], 3)
        self.assertEqual(response.data['stats']['triggers'], 1)

    def test_broken_graph_is_reported_not_hidden(self):
        tree = dict(default_tree())
        tree[LOGIC_KEY] = {'nodes': [{'id': 'a', 'type': 'action.нет'}],
                           'edges': []}
        self.project.tree = tree
        self.project.save()
        self.login()
        response = self.client.get(f'/api/projects/{self.project.id}/logic/')
        self.assertFalse(response.data['valid'])
        self.assertIn('неизвестный тип', ' '.join(response.data['problems']))

    def test_check_returns_script(self):
        self.login()
        response = self.client.post(
            f'/api/projects/{self.project.id}/logic/check/',
            {'graph': GRAPH}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Спасибо за заказ', response.data['script'])

    def test_check_refuses_broken_graph(self):
        self.login()
        response = self.client.post(
            f'/api/projects/{self.project.id}/logic/check/',
            {'graph': {'nodes': [{'id': 'a', 'type': 'action.нет'}],
                       'edges': []}}, format='json')
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.data['valid'])

    def test_outsider_sees_nothing(self):
        outsider = User.objects.create_user('outsider', password='pass-x')
        self.login('outsider', 'pass-x')
        response = self.client.get(f'/api/projects/{self.project.id}/logic/')
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_refused(self):
        response = APIClient().get('/api/logic/types/')
        self.assertEqual(response.status_code, 401)