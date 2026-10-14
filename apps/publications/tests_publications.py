"""Публикация сайта на инфраструктуре платформы (сценарий 1, ТЗ п.16.3).

Проверяется то, что ломается дороже всего: посетитель не должен
увидеть половину сборки, отозванный сайт — остаться доступным, а
чужая папка — не отдаваться по адресу.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Membership
from projects.models import Project
from projects.versions import snapshot

from publications.models import Site
from publications.service import (
    PublishError,
    SiteNotFound,
    backup_site,
    publish,
    resolve,
    status_payload,
    withdraw,
)


def block(text: str = 'Заголовок') -> dict:
    return {
        'id': 'b1', 'module': 'text.heading', 'x': 0, 'y': 0,
        'width': 600, 'height': 200, 'label': 'Блок',
        'props': {'text': text},
    }


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class PublishTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(
            PUBLISH_ROOT=Path(self.tmp.name), PUBLICATION_BASE_URL=''
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

        User = get_user_model()
        self.user = User.objects.create_user('owner', password='pass-owner')
        self.project = Project.objects.create(
            owner=self.user, name='Цветы', tree={'width': 1200, 'blocks': []}
        )
        self.project.tree = {'width': 1200, 'blocks': [block()]}
        self.project.version += 1
        self.project.save(update_fields=['tree', 'version'])
        self.version = snapshot(self.project, self.project.tree,
                                author=self.user, label='v1')

    def next_version(self, text: str) -> None:
        self.project.version += 1
        self.project.tree = {'width': 1200, 'blocks': [block(text)]}
        self.project.save(update_fields=['tree', 'version'])
        self.version = snapshot(self.project, self.project.tree,
                                author=self.user, label=f'v{self.project.version}')

    def client_for(self, user=None, password='pass-owner'):
        client = APIClient()
        response = client.post(
            '/api/auth/login/',
            {'login': (user or self.user).username, 'password': password},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}'
        )
        return client

    # --- публикация ---------------------------------------------------

    def test_publish_creates_site(self):
        result = publish(self.project, self.version)
        self.assertEqual(result.site.slug, 'site')
        self.assertEqual(result.site.state, 'active')
        self.assertGreater(result.files, 5)

    def test_publish_places_files_on_disk(self):
        result = publish(self.project, self.version)
        index = result.version.directory / 'index.html'
        self.assertTrue(index.exists())
        self.assertIn('Заголовок', index.read_text(encoding='utf-8'))

    def test_slug_comes_from_name(self):
        self.project.name = 'my-shop'
        self.project.save(update_fields=['name'])
        self.assertEqual(publish(self.project, self.version).site.slug, 'my-shop')

    def test_cyrillic_name_still_gets_address(self):
        """Название без латиницы должно давать адрес, а не отказ:
        иначе публикация недоступна половине клиентов."""
        self.project.name = 'Цветы и розы'
        self.project.save(update_fields=['name'])
        self.assertEqual(publish(self.project, self.version).site.slug, 'site')

    def test_addresses_do_not_collide(self):
        """Два проекта с одинаковым названием не должны делить адрес."""
        other = Project.objects.create(
            owner=self.user, name='Цветы', tree={'width': 1200, 'blocks': []}
        )
        other.version += 1
        other.save(update_fields=['version'])
        first = publish(self.project, self.version)
        second = publish(other, snapshot(other, other.tree, author=self.user))
        self.assertNotEqual(first.site.slug, second.site.slug)

    def test_republish_switches_version(self):
        publish(self.project, self.version)
        self.next_version('Новый заголовок')
        result = publish(self.project, self.version)

        self.assertEqual(result.version.number, self.version.number)
        html = (result.version.directory / 'index.html').read_text(encoding='utf-8')
        self.assertIn('Новый заголовок', html)

    def test_republish_of_same_version_is_cheap(self):
        first = publish(self.project, self.version)
        again = publish(self.project, self.version)
        self.assertTrue(again.warnings)
        self.assertEqual(first.version.id, again.version.id)

    def test_old_versions_are_kept_for_rollback(self):
        for index in range(4):
            self.next_version(f'Версия {index}')
            publish(self.project, self.version)
        site = Site.objects.get()
        self.assertGreaterEqual(site.versions.count(), 2)
        self.assertTrue(site.current_version)

    # --- раздача -------------------------------------------------------

    def test_site_is_served_by_address(self):
        result = publish(self.project, self.version)
        response = self.client.get(f'/sites/{result.site.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Заголовок', response.content.decode('utf-8'))

    def test_served_file_carries_version(self):
        result = publish(self.project, self.version)
        response = self.client.get(f'/sites/{result.site.slug}/')
        self.assertEqual(response['X-AuraBuilder-Version'],
                         str(result.version.number))

    def test_assets_are_served(self):
        result = publish(self.project, self.version)
        response = self.client.get(f'/sites/{result.site.slug}/assets/css/site.css')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/css', response['Content-Type'])

    def test_unknown_address_is_404(self):
        self.assertEqual(self.client.get('/sites/нет-такого/').status_code, 404)

    def test_path_outside_site_is_refused(self):
        """Путь вида ../../secret не должен приводить к чтению чужих
        файлов за пределами папки сайта."""
        result = publish(self.project, self.version)
        response = self.client.get(f'/sites/{result.site.slug}/../../settings.py')
        self.assertIn(response.status_code, (400, 404))

    def test_python_files_are_not_served(self):
        """В папке сайта нет исполняемого кода, но правило страхует от
        ошибки в будущем."""
        result = publish(self.project, self.version)
        hidden = result.version.directory / 'secret.py'
        hidden.write_text('пароль = 1', encoding='utf-8')
        response = self.client.get(f'/sites/{result.site.slug}/secret.py')
        self.assertEqual(response.status_code, 404)

    def test_requests_are_counted(self):
        result = publish(self.project, self.version)
        self.client.get(f'/sites/{result.site.slug}/')
        self.client.get(f'/sites/{result.site.slug}/')
        site = Site.objects.get(pk=result.site.pk)
        self.assertEqual(site.requests, 2)
        self.assertIsNotNone(site.last_request_at)

    # --- отзыв ---------------------------------------------------------

    def test_withdraw_stops_serving(self):
        result = publish(self.project, self.version)
        withdraw(result.site)
        response = self.client.get(f'/sites/{result.site.slug}/')
        # 410, а не 404: сайт был и был отозван.
        self.assertEqual(response.status_code, 410)

    def test_withdraw_can_be_reverted_by_publishing_again(self):
        result = publish(self.project, self.version)
        withdraw(result.site)
        again = publish(self.project, self.version)
        self.assertTrue(again.site.is_active)
        self.assertEqual(self.client.get(f'/sites/{again.site.slug}/').status_code, 200)

    def test_withdraw_keeps_files_by_default(self):
        """Отзыв обратим: удалять сайт по кнопке — плохая идея."""
        result = publish(self.project, self.version)
        directory = result.version.directory
        withdraw(result.site)
        self.assertTrue(directory.exists())

    # --- копии ---------------------------------------------------------

    def test_backup_is_independent_copy(self):
        result = publish(self.project, self.version)
        backup = backup_site(result.site)
        self.assertIsNotNone(backup)
        self.assertTrue((backup.directory / 'index.html').exists())
        # Копия снимок байтов: удаление файлов сайта не должно убить её.
        import shutil

        shutil.rmtree(result.version.directory)
        self.assertTrue((backup.directory / 'index.html').exists())

    def test_backup_without_version_is_none(self):
        site = Site.objects.create(project=self.project, slug='site')
        self.assertIsNone(backup_site(site))

    # --- API -----------------------------------------------------------

    def test_api_publishes(self):
        client = self.client_for()
        response = client.post(f'/api/projects/{self.project.id}/site/', {}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['active'])
        self.assertIn('/sites/', response.data['url'])

    def test_api_reports_unpublished(self):
        client = self.client_for()
        response = client.get(f'/api/projects/{self.project.id}/site/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['published'])

    def test_api_requires_publish_right(self):
        editor = get_user_model().objects.create_user('editor', password='pass-e')
        Membership.objects.create(project=self.project, user=editor, role='editor')
        client = self.client_for(editor, 'pass-e')
        response = client.post(f'/api/projects/{self.project.id}/site/', {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_api_withdraws(self):
        client = self.client_for()
        client.post(f'/api/projects/{self.project.id}/site/', {}, format='json')
        response = client.post(f'/api/projects/{self.project.id}/site/withdraw/',
                               {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['active'])

    def test_api_without_versions_is_409(self):
        client = self.client_for()
        self.project.versions.all().delete()
        response = client.post(f'/api/projects/{self.project.id}/site/', {}, format='json')
        self.assertEqual(response.status_code, 409)

    def test_api_status_includes_versions_and_backups(self):
        client = self.client_for()
        client.post(f'/api/projects/{self.project.id}/site/', {}, format='json')
        client.post(f'/api/projects/{self.project.id}/site/backup/', {}, format='json')
        payload = status_payload(Site.objects.get())
        self.assertTrue(payload['currentVersion'])
        self.assertEqual(payload['backups'], 1)


class ResolveTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(
            PUBLISH_ROOT=Path(self.tmp.name), PUBLICATION_BASE_URL=''
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_missing_site_raises(self):
        with self.assertRaises(SiteNotFound):
            resolve('нет', '')

    def test_site_without_version_raises(self):
        user = get_user_model().objects.create_user('u', password='x')
        project = Project.objects.create(owner=user, name='П', tree={'width': 1200,
                                                                    'blocks': []})
        Site.objects.create(project=project, slug='p')
        with self.assertRaises(SiteNotFound):
            resolve('p', '')


class SlugTests(TestCase):
    def test_underscores_and_spaces_are_replaced(self):
        from publications.models import slugify_site_name

        self.assertEqual(slugify_site_name('My Shop_2'), 'my-shop-2')

    def test_long_name_is_cut(self):
        from publications.models import slugify_site_name

        result = slugify_site_name('a' * 200)
        self.assertLessEqual(len(result), 63)

    def test_empty_name_falls_back(self):
        from publications.models import slugify_site_name

        self.assertEqual(slugify_site_name(''), 'site')