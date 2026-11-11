"""MCP-эндпоинт: согласование версии, инструменты и их ошибки.

Тесты идут через HTTP, как настоящий клиент: MCP — это транспортный
контракт, и проверять его на уровне функций значило бы не заметить,
что представление отвечает не тем кодом или не тем телом.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import Subscription
from projects.models import DocumentVersion, Page, Project, default_tree

User = get_user_model()


class McpBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('mcpuser', 'mcp@example.com', 'verysecret123')
        Subscription.objects.create(user=self.user, plan='start')
        self.project = Project.objects.create(
            name='Ромашка', tree=default_tree(), owner=self.user, version=1,
        )
        Page.objects.create(
            project=self.project, title='Услуги', slug='uslugi', order=1,
        )
        DocumentVersion.objects.create(
            project=self.project, number=1, tree=self.project.tree, author=self.user,
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'mcpuser', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def rpc(self, method, params=None, request_id=1):
        payload = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
        if params is not None:
            payload['params'] = params
        return self.client.post('/api/v1/mcp/', payload, format='json')

    def call(self, name, arguments=None):
        return self.rpc(
            'tools/call',
            {'name': name, 'arguments': arguments or {}},
        )


class McpHandshakeTests(McpBase):
    def test_initialize_echoes_supported_version(self):
        response = self.rpc(
            'initialize',
            {'protocolVersion': '2025-06-18', 'clientInfo': {'name': 'test'}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(
            response.data['result']['serverInfo']['name'], 'aurabuilder',
        )
        self.assertIn('tools', response.data['result']['capabilities'])

    def test_unknown_version_gets_latest(self):
        response = self.rpc('initialize', {'protocolVersion': '1999-01-01'})
        self.assertEqual(response.data['result']['protocolVersion'], '2025-11-25')

    def test_notification_gets_no_body(self):
        response = self.client.post(
            '/api/v1/mcp/',
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.content, b'')

    def test_ping(self):
        response = self.rpc('ping')
        self.assertEqual(response.data['result'], {})

    def test_authentication_is_required(self):
        anonymous = self.client_class()
        response = anonymous.post(
            '/api/v1/mcp/',
            {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_parse_error_is_jsonrpc_error(self):
        response = self.client.generic(
            'POST', '/api/v1/mcp/', data='{', content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error']['code'], -32700)

    def test_batch_is_rejected(self):
        response = self.client.post(
            '/api/v1/mcp/',
            [{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}],
            format='json',
        )
        self.assertEqual(response.data['error']['code'], -32600)

    def test_unknown_method(self):
        response = self.rpc('tools/unknown')
        self.assertEqual(response.data['error']['code'], -32601)


class McpToolsTests(McpBase):
    def test_tools_list_is_read_only(self):
        response = self.rpc('tools/list')
        tools = response.data['result']['tools']
        names = {tool['name'] for tool in tools}
        self.assertEqual(
            names,
            {
                'list_projects',
                'get_project',
                'list_pages',
                'get_page',
                'list_versions',
                'export_summary',
            },
        )
        for tool in tools:
            self.assertEqual(tool['inputSchema']['type'], 'object')

    def test_list_projects(self):
        response = self.call('list_projects')
        result = response.data['result']
        self.assertFalse(result['isError'])
        projects = result['structuredContent']['projects']
        self.assertEqual([item['id'] for item in projects], [str(self.project.id)])
        self.assertIn('Ромашка', result['content'][0]['text'])

    def test_get_project_returns_tree(self):
        response = self.call('get_project', {'projectId': str(self.project.id)})
        data = response.data['result']['structuredContent']
        self.assertEqual(data['id'], str(self.project.id))
        self.assertIn('tree', data)

    def test_get_page_by_slug(self):
        response = self.call(
            'get_page', {'projectId': str(self.project.id), 'slug': 'uslugi'},
        )
        data = response.data['result']['structuredContent']
        self.assertEqual(data['slug'], 'uslugi')
        self.assertIn('tree', data)

    def test_get_home_page(self):
        response = self.call(
            'get_page', {'projectId': str(self.project.id), 'slug': ''},
        )
        data = response.data['result']['structuredContent']
        self.assertTrue(data['isHome'])

    def test_tool_error_is_not_rpc_error(self):
        response = self.call('get_project', {'projectId': 'нет-такого'})
        result = response.data['result']
        self.assertTrue(result['isError'])
        self.assertIn('не найден', result['content'][0]['text'])

    def test_missing_project_id_is_tool_error(self):
        response = self.call('get_project', {})
        self.assertTrue(response.data['result']['isError'])

    def test_unknown_tool_is_invalid_params(self):
        response = self.call('delete_everything')
        self.assertEqual(response.data['error']['code'], -32602)

    def test_export_summary(self):
        response = self.call(
            'export_summary',
            {'projectId': str(self.project.id), 'version': 1},
        )
        data = response.data['result']['structuredContent']
        self.assertFalse(response.data['result']['isError'])
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['formatVersion'], 1)
        self.assertGreater(data['fileCount'], 0)
        self.assertIn('/api/v1/projects/', data['download'])
        self.assertNotIn('manifest', data)

    def test_export_summary_can_include_manifest(self):
        response = self.call(
            'export_summary',
            {'projectId': str(self.project.id), 'includeManifest': True},
        )
        data = response.data['result']['structuredContent']
        self.assertIn('manifest', data)
        self.assertIn('files', data['manifest'])
