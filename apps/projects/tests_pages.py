"""Многостраничность: API страниц, снимки и экспорт (ТЗ п.3.2, п.16.4)."""

import io
import json
import zipfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import Subscription
from projects.models import DocumentVersion, Page, Project, default_tree

User = get_user_model()


class PageApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'pages', 'pages@example.com', 'verysecret123',
        )
        Subscription.objects.create(user=self.user, plan='start')
        self.project = Project.objects.create(
            name='Сайт студии', tree=default_tree(), owner=self.user,
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'pages', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}',
        )
        self.url = f'/api/projects/{self.project.id}/pages/'

    def create(self, title='О нас'):
        return self.client.post(self.url, {'title': title}, format='json')

    def test_create_transliterates_slug_and_snapshots(self):
        response = self.create('О нас')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['slug'], 'o-nas')
        self.assertEqual(response.data['version'], 1)
        self.assertEqual(response.data['projectVersion'], 2)

        page = Page.objects.get(project=self.project)
        self.assertEqual(page.title, 'О нас')
        version = DocumentVersion.objects.get(project=self.project, number=2)
        self.assertEqual(version.pages[0]['slug'], 'o-nas')

    def test_duplicate_title_gets_free_slug(self):
        self.create('Контакты')
        response = self.create('Контакты')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'kontakty-2')

    def test_project_payload_lists_pages_without_trees(self):
        self.create('Услуги')
        response = self.client.get(f'/api/projects/{self.project.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['pages']), 1)
        self.assertEqual(response.data['pages'][0]['slug'], 'uslugi')
        self.assertNotIn('tree', response.data['pages'][0])

    def test_stale_version_is_conflict(self):
        page_id = self.create().data['id']
        url = f'{self.url}{page_id}/'
        tree = default_tree()
        tree['blocks'][0]['label'] = 'Новый первый экран'
        response = self.client.put(
            url, {'tree': tree, 'expectedVersion': 99}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['version'], 1)

    def test_update_increments_version_and_keeps_pages_in_snapshot(self):
        created = self.create().data
        tree = default_tree()
        tree['blocks'][0]['label'] = 'Обновлено'
        response = self.client.patch(
            f'{self.url}{created["id"]}/',
            {'tree': tree, 'expectedVersion': created['version']},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['version'], 2)
        latest = DocumentVersion.objects.filter(project=self.project).first()
        self.assertEqual(latest.pages[0]['tree']['blocks'][0]['label'], 'Обновлено')

    def test_delete_removes_page_and_records_snapshot(self):
        page_id = self.create().data['id']
        response = self.client.delete(f'{self.url}{page_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Page.objects.filter(pk=page_id).exists())
        latest = DocumentVersion.objects.filter(project=self.project).first()
        self.assertEqual(latest.pages, [])

    def test_restore_brings_deleted_page_back(self):
        page_id = self.create('Новости').data['id']
        self.project.refresh_from_db()
        with_page = self.project.version
        self.client.delete(f'{self.url}{page_id}/')
        self.assertEqual(Page.objects.count(), 0)

        response = self.client.post(
            f'/api/projects/{self.project.id}/versions/{with_page}/restore/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        restored = Page.objects.get(project=self.project)
        self.assertEqual(restored.title, 'Новости')
        self.assertEqual(restored.slug, 'novosti')

    def test_reserved_title_gets_free_slug(self):
        response = self.create('API')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['slug'], 'api-2')

    def test_reserved_slug_is_rejected(self):
        response = self.client.post(
            self.url, {'title': 'API', 'slug': 'api'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('slug', response.data)


class PageLimitTests(APITestCase):
    """Главная тоже занимает место в тарифе."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'free', 'free@example.com', 'verysecret123',
        )
        self.project = Project.objects.create(
            name='Бесплатный', tree=default_tree(), owner=self.user,
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'free', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}',
        )

    def test_free_plan_allows_five_pages_total(self):
        url = f'/api/projects/{self.project.id}/pages/'
        for index in range(4):
            response = self.client.post(url, {'title': f'Страница {index}'}, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        response = self.client.post(url, {'title': 'Лишняя'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data['reason'], 'page_limit')


class MultiPageExportTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'exporter', 'exporter@example.com', 'verysecret123',
        )
        Subscription.objects.create(user=self.user, plan='start')
        self.project = Project.objects.create(
            name='Магазин', tree=default_tree(), owner=self.user,
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'exporter', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}',
        )
        created = self.client.post(
            f'/api/projects/{self.project.id}/pages/',
            {'title': 'О нас', 'seoTitle': 'О студии', 'seoDescription': 'Кто мы'},
            format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.page = created.data

    def archive(self) -> zipfile.ZipFile:
        response = self.client.get(f'/api/projects/{self.project.id}/export/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return zipfile.ZipFile(io.BytesIO(response.content))

    def test_archive_contains_page_and_its_assets(self):
        archive = self.archive()
        names = set(archive.namelist())
        self.assertIn('o-nas/index.html', names)
        html = archive.read('o-nas/index.html').decode('utf-8')
        self.assertIn('../assets/css/site.css', html)
        self.assertIn('<title>О студии</title>', html)
        self.assertIn('<a href="../">Магазин</a>', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('aria-label="Страницы сайта"', html)

    def test_home_links_to_page_and_sitemap_lists_it(self):
        archive = self.archive()
        home = archive.read('index.html').decode('utf-8')
        self.assertIn('href="o-nas/"', home)
        sitemap = archive.read('sitemap.xml').decode('utf-8')
        self.assertIn('/o-nas/', sitemap)

    def test_manifest_lists_pages(self):
        archive = self.archive()
        manifest = json.loads(archive.read('build-manifest.json'))
        slugs = [page['slug'] for page in manifest['pages']]
        self.assertEqual(slugs, ['', 'o-nas'])


