"""Публичный API v1: доступ, форма ответа и выгрузка.

Проверяется контракт, а не внутренние функции: клиент видит только
HTTP-статусы, поля и формат ошибок. Если однажды ответ изменится,
сломается этот тест — и это правильный сигнал, потому что версия v1
обещает совместимость.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership, Role
from billing.models import Subscription
from projects.models import DocumentVersion, Page, Project, default_tree

User = get_user_model()


class ApiV1Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('apiuser', 'api@example.com', 'verysecret123')
        Subscription.objects.create(user=self.user, plan='start')
        self.project = Project.objects.create(
            name='Ромашка', tree=default_tree(), owner=self.user, version=1,
        )
        self.other = Project.objects.create(
            name='Чужой', tree=default_tree(), owner=self.other_user(), version=1,
        )
        self.page = Page.objects.create(
            project=self.project,
            title='Услуги',
            slug='uslugi',
            tree=default_tree(),
            order=1,
        )
        self.version = DocumentVersion.objects.create(
            project=self.project,
            number=1,
            tree=self.project.tree,
            pages=[{'slug': 'uslugi', 'title': 'Услуги', 'tree': self.page.tree}],
            author=self.user,
        )
        self.login()

    def other_user(self):
        # Отдельный пользователь на каждый вызов setUp: тесты не должны
        # делить владельца чужого проекта.
        if not hasattr(self, '_other_user'):
            self._other_user = User.objects.create_user(
                'stranger', 'stranger@example.com', 'verysecret123',
            )
        return self._other_user

    def login(self):
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'apiuser', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}',
        )


class ApiV1ReadTests(ApiV1Base):
    def test_index_is_public_and_names_version(self):
        anonymous = self.client_class()
        response = anonymous.get('/api/v1/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['apiVersion'], 1)
        self.assertEqual(response['X-API-Version'], '1')
        self.assertIn('mcp', response.data)

    def test_authentication_is_required(self):
        anonymous = self.client_class()
        response = anonymous.get('/api/v1/projects/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['error']['code'], 'unauthorized')
        self.assertEqual(response['X-API-Version'], '1')

    def test_list_contains_only_readable_projects(self):
        response = self.client.get('/api/v1/projects/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data['data']]
        self.assertEqual(ids, [str(self.project.id)])
        self.assertEqual(response.data['meta']['total'], 1)
        self.assertEqual(response.data['data'][0]['role'], Role.OWNER)

    def test_member_sees_project(self):
        viewer = User.objects.create_user('viewer', 'viewer@example.com', 'verysecret123')
        Membership.objects.create(project=self.project, user=viewer, role=Role.VIEWER)
        login = self.client.post(
            '/api/auth/login/',
            {'login': 'viewer', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        response = self.client.get(f'/api/v1/projects/{self.project.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['role'], Role.VIEWER)

    def test_foreign_project_is_not_found(self):
        response = self.client.get(f'/api/v1/projects/{self.other.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['error']['code'], 'not_found')

    def test_bad_uuid_is_the_same_not_found(self):
        response = self.client.get('/api/v1/projects/not-a-uuid/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['error']['code'], 'not_found')

    def test_detail_includes_tree_brand_and_pages(self):
        response = self.client.get(f'/api/v1/projects/{self.project.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Ромашка')
        self.assertIn('tree', response.data)
        self.assertIn('brand', response.data)
        self.assertEqual(response.data['pageCount'], 2)
        self.assertEqual(response.data['pages'][0]['slug'], 'uslugi')

    def test_pages_include_home_first(self):
        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/pages/',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pages = response.data['pages']
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0]['slug'], '')
        self.assertTrue(pages[0]['isHome'])
        self.assertEqual(pages[1]['slug'], 'uslugi')

    def test_page_detail_returns_tree(self):
        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/pages/uslugi/',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Услуги')
        self.assertIn('tree', response.data)

    def test_missing_page_is_not_found(self):
        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/pages/net/',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_versions_have_no_trees(self):
        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/versions/',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['versions'][0]
        self.assertEqual(item['number'], 1)
        self.assertNotIn('tree', item)
        self.assertEqual(item['pageCount'], 2)

    def test_bad_pagination_is_rejected(self):
        response = self.client.get('/api/v1/projects/?limit=999')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error']['code'], 'invalid_request')

    def test_method_not_allowed_uses_error_envelope(self):
        response = self.client.post('/api/v1/projects/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.data['error']['code'], 'method_not_allowed')


class ApiV1ExportTests(ApiV1Base):
    def test_export_returns_zip(self):
        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/export/?version=1',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertEqual(response['X-AuraBuilder-Version'], '1')
        self.assertEqual(response['X-API-Version'], '1')
        self.assertTrue(response.content.startswith(b'PK'))

    def test_project_without_versions_conflicts(self):
        empty = Project.objects.create(
            name='Пустой', tree=default_tree(), owner=self.user, version=1,
        )
        response = self.client.get(f'/api/v1/projects/{empty.id}/export/')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['error']['code'], 'conflict')

    def test_missing_version_is_not_found(self):
        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/export/?version=99',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_viewer_cannot_export(self):
        viewer = User.objects.create_user('viewer2', 'viewer2@example.com', 'verysecret123')
        Membership.objects.create(project=self.project, user=viewer, role=Role.VIEWER)
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'viewer2', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        response = self.client.get(f'/api/v1/projects/{self.project.id}/export/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'forbidden')
