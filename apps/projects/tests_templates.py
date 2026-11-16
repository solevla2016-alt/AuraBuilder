"""Шаблоны страниц и блоков: снимки удачных решений (этап 2).

Проверяется главное свойство шаблона — он снимок, а не ссылка, — и то,
что чужой проект не может ни прочитать шаблоны, ни сохранить свой.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership
from accounts.permissions import Role
from billing.models import Subscription
from projects.models import (
    MAX_TEMPLATES,
    TEMPLATE_BLOCK,
    TEMPLATE_PAGE,
    Page,
    Project,
    Template,
    default_tree,
)

User = get_user_model()


class TemplateApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'templates', 'templates@example.com', 'verysecret123',
        )
        Subscription.objects.create(user=self.user, plan='start')
        self.project = Project.objects.create(
            name='Сайт студии', tree=default_tree(), owner=self.user,
        )
        self.page = Page.objects.create(
            project=self.project,
            title='О нас',
            slug='o-nas',
            tree={
                'width': 720,
                'blocks': [
                    {'id': 'about1', 'module': 'text.heading', 'x': 40,
                     'y': 40, 'width': 640, 'height': 64, 'label': 'О нас'},
                ],
            },
            seo_title='О студии',
            seo_description='Кто мы',
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'templates', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}',
        )
        self.url = f'/api/projects/{self.project.id}/templates/'

    def create(self, **payload):
        payload.setdefault('name', 'Удачная страница')
        payload.setdefault('kind', TEMPLATE_PAGE)
        return self.client.post(self.url, payload, format='json')

    # --- сохранение ----------------------------------------------------

    def test_page_template_copies_main_page(self):
        response = self.create()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         response.data)
        self.assertEqual(response.data['kind'], TEMPLATE_PAGE)
        self.assertEqual(response.data['blocks'], len(default_tree()['blocks']))
        self.assertEqual(response.data['title'], 'Сайт студии')
        self.assertEqual(response.data['tree'], default_tree())

    def test_page_template_copies_inner_page_and_seo(self):
        response = self.create(page=str(self.page.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         response.data)
        self.assertEqual(response.data['title'], 'О нас')
        self.assertEqual(response.data['meta']['slug'], 'o-nas')
        self.assertEqual(response.data['meta']['seoTitle'], 'О студии')
        self.assertEqual(response.data['tree'], self.page.tree)

    def test_template_is_a_snapshot(self):
        """Правка страницы после сохранения не меняет шаблон: иначе
        «удачным решением» оказалось бы текущее состояние."""
        created = self.create().data
        tree = default_tree()
        tree['blocks'][0]['label'] = 'Переделали'
        self.project.tree = tree
        self.project.save(update_fields=['tree'])

        detail = self.client.get(f'{self.url}{created["id"]}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
        self.assertEqual(detail.data['tree']['blocks'][0]['label'],
                         'Первый экран')

    def test_block_template_copies_one_block(self):
        response = self.create(
            name='Мой заголовок', kind=TEMPLATE_BLOCK,
            page=str(self.page.id), block='about1',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         response.data)
        self.assertEqual(response.data['module'], 'text.heading')
        self.assertEqual(response.data['tree']['id'], 'about1')
        self.assertEqual(response.data['tree']['label'], 'О нас')

    def test_block_template_from_main_page(self):
        """Блок с главной: её дерево лежит в проекте, а не в Page, но
        запрещать сохранять с неё блоки нельзя — это первая страница."""
        response = self.create(name='Первый экран', kind=TEMPLATE_BLOCK,
                               block='b1')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         response.data)
        self.assertEqual(response.data['module'], 'section.hero')
        self.assertEqual(response.data['title'], 'Сайт студии')

    def test_block_template_without_block_is_404(self):
        response = self.create(name='Блок', kind=TEMPLATE_BLOCK,
                               page=str(self.page.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND,
                         response.data)

    def test_unknown_block_is_404(self):
        response = self.create(name='Блок', kind=TEMPLATE_BLOCK,
                               page=str(self.page.id), block='нет')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND,
                         response.data)

    def test_unknown_page_is_404(self):
        response = self.create(page='00000000-0000-4000-8000-000000000099')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND,
                         response.data)

    def test_empty_name_is_400(self):
        response = self.create(name='   ')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         response.data)

    def test_unknown_kind_is_400(self):
        response = self.create(kind='video')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         response.data)

    # --- список и удаление --------------------------------------------

    def test_list_returns_summaries_newest_first(self):
        self.create(name='Первый')
        self.create(name='Второй')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['templates'][0]['name'], 'Второй')
        self.assertNotIn('tree', response.data['templates'][0])
        self.assertEqual(response.data['limit'], MAX_TEMPLATES)

    def test_detail_returns_tree(self):
        created = self.create().data
        response = self.client.get(f'{self.url}{created["id"]}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('tree', response.data)
        self.assertIn('meta', response.data)

    def test_delete_removes_template(self):
        created = self.create().data
        response = self.client.delete(f'{self.url}{created["id"]}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Template.objects.exists())

    def test_delete_of_unknown_is_404(self):
        response = self.client.delete(
            f'{self.url}00000000-0000-4000-8000-000000000099/'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_limit_is_enforced(self):
        for index in range(MAX_TEMPLATES):
            Template.objects.create(
                project=self.project, kind=TEMPLATE_PAGE,
                name=f'Шаблон {index}', tree=default_tree(),
            )
        response = self.create(name='Лишний')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT,
                         response.data)

    # --- права и границы ----------------------------------------------

    def test_viewer_can_list_but_not_create(self):
        viewer = User.objects.create_user('viewer', password='pass-viewer')
        Membership.objects.create(
            project=self.project, user=viewer, role=Role.VIEWER,
        )
        client = self.client_class()
        login = client.post(
            '/api/auth/login/',
            {'login': 'viewer', 'password': 'pass-viewer'}, format='json',
        )
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}',
        )

        listing = client.get(self.url)
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        response = client.post(
            self.url, {'name': 'Чужой', 'kind': TEMPLATE_PAGE},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_project_is_404(self):
        stranger = User.objects.create_user('stranger', password='pass-s')
        client = self.client_class()
        login = client.post(
            '/api/auth/login/',
            {'login': 'stranger', 'password': 'pass-s'}, format='json',
        )
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}',
        )
        response = client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_is_refused(self):
        client = self.client_class()
        response = client.get(self.url)
        self.assertIn(response.status_code,
                      (status.HTTP_401_UNAUTHORIZED,
                       status.HTTP_403_FORBIDDEN))

    def test_page_can_be_created_from_template_tree(self):
        """Шаблон применяется обычным созданием страницы: отдельного
        «применить» нет, чтобы права и лимиты проверялись в одном месте."""
        created = self.create().data
        response = self.client.post(
            f'/api/projects/{self.project.id}/pages/',
            {'title': 'Новый лендинг', 'tree': created['tree']},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         response.data)
        self.assertEqual(response.data['slug'], 'novyy-lending')
        self.assertEqual(len(response.data['tree']['blocks']),
                         len(default_tree()['blocks']))
