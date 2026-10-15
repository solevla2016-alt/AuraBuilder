"""Сценарий 4, часть PWA (ТЗ п.16.6).

Проверяется то, на чём всё держится: манифест и service worker должны
есть, обращаться только к своим файлам и не кешировать то, что меняется
по запросу. Иначе покупатель увидит свой старый заказ как действующий.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from projects.models import Project
from projects.package import build_package
from projects.pwa import manifest, service_worker
from projects.versions import snapshot
from billing.models import Subscription


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class PwaPackageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('owner', password='pass-owner')
        Subscription.objects.create(user=self.user, plan='pro')
        tree = {'width': 1200, 'blocks': [{
            'id': 'b1', 'module': 'text.heading', 'x': 0, 'y': 0,
            'width': 600, 'height': 200, 'label': 'Блок',
            'props': {'text': 'Привет'},
        }]}
        self.project = Project.objects.create(
            owner=self.user, name='Цветы', tree={'width': 1200, 'blocks': []}
        )
        self.project.tree = tree
        self.project.version += 1
        self.project.save(update_fields=['tree', 'version'])
        self.version = snapshot(self.project, tree, author=self.user, label='v1')

    def build(self, pwa: bool):
        return build_package(self.project, self.version,
                             base_url='https://shop.example', pwa=pwa)

    def client_for(self):
        client = APIClient()
        response = client.post(
            '/api/auth/login/',
            {'login': 'owner', 'password': 'pass-owner'}, format='json',
        )
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}'
        )
        return client

    # --- что входит в пакет -----------------------------------------

    def test_pwa_is_off_by_default(self):
        """Без явного включения пакет остаётся обычным сайтом: лишняя
        регистрация service worker расходует память телефона."""
        files = self.build(False)['files']
        self.assertNotIn('manifest.json', files)
        self.assertNotIn('service-worker.js', files)

    def test_pwa_files_are_added(self):
        files = self.build(True)['files']
        for name in ('manifest.json', 'service-worker.js',
                     'assets/icons/icon.svg', 'assets/icons/icon-maskable.svg'):
            self.assertIn(name, files)

    def test_page_links_manifest_only_when_enabled(self):
        self.assertNotIn('rel="manifest"', self.build(False)['files']['index.html'])
        self.assertIn('rel="manifest"', self.build(True)['files']['index.html'])

    def test_manifest_is_marked_in_build_manifest(self):
        self.assertFalse(self.build(False)['manifest']['pwa'])
        self.assertTrue(self.build(True)['manifest']['pwa'])

    # --- содержимое --------------------------------------------------

    def test_manifest_describes_app(self):
        data = json.loads(self.build(True)['files']['manifest.json'])
        self.assertEqual(data['name'], 'Цветы')
        self.assertEqual(data['display'], 'standalone')
        self.assertEqual(data['lang'], 'ru')
        self.assertEqual(len(data['icons']), 2)
        purposes = {icon['purpose'] for icon in data['icons']}
        self.assertEqual(purposes, {'any', 'maskable'})

    def test_manifest_colors_come_from_palette(self):
        from component_library.models import ComponentStyle

        ComponentStyle.objects.create(
            project=self.project, kind='section',
            tokens={'background': '#123456', 'text': '#FEDCBA', 'radius': 8,
                    'padding': 20, 'weight': 400, 'border': 1},
        )
        data = json.loads(self.build(True)['files']['manifest.json'])
        self.assertEqual(data['theme_color'], '#123456')
        self.assertEqual(data['background_color'], '#FEDCBA')

    def test_icon_has_no_external_references(self):
        # xmlns в SVG — это обязательное имя пространства, а не
        # обращение к сети: внешних ссылок в иконке быть не должно.
        icon = self.build(True)['files']['assets/icons/icon.svg']
        for pattern in ('src=', 'href=', 'url(', '<image'):
            self.assertNotIn(pattern, icon)
        self.assertIn('<svg', icon)

    def test_service_worker_precaches_only_package_files(self):
        worker = self.build(True)['files']['service-worker.js']
        self.assertIn('"index.html"', worker)
        self.assertIn('assets/css/site.css', worker)
        # Кешировать всё подряд нельзя: иначе офлайн покажет старый сайт.
        self.assertNotIn("'assets/data/data.json'", worker)

    def test_service_worker_skips_api(self):
        """Запросы к рантайму не кешируются никогда: иначе покупатель
        увидит свою корзину из прошлого визита."""
        worker = self.build(True)['files']['service-worker.js']
        self.assertIn("url.pathname.startsWith('/api/')", worker)

    def test_service_worker_cache_changes_with_version(self):
        first = self.build(True)['files']['service-worker.js']
        self.assertIn(f'v{self.version.number}', first)

        tree = {'width': 1200, 'blocks': []}
        self.project.version += 1
        self.project.save(update_fields=['version'])
        second_version = snapshot(self.project, tree, author=self.user, label='v2')
        built = build_package(self.project, second_version,
                               base_url='https://shop.example', pwa=True)
        self.assertIn(f'v{second_version.number}',
                      built['files']['service-worker.js'])
        self.assertNotIn(f'v{self.version.number}',
                         built['files']['service-worker.js'])

    def test_old_cache_is_dropped_on_activate(self):
        """Кеш прошлой версии удаляется, иначе телефон копил бы копии
        сайта, которых никто не выгружал заново."""
        worker = self.build(True)['files']['service-worker.js']
        self.assertIn('caches.delete', worker)

    def test_service_worker_serves_cache_when_offline(self):
        worker = self.build(True)['files']['service-worker.js']
        self.assertIn('.catch(() => cached)', worker)


class PwaHelpersTests(TestCase):
    def test_manifest_escapes_project_name(self):
        data = json.loads(manifest('Кафе «Уют» & Co', 'index.html', '#000', '#fff'))
        self.assertEqual(data['name'], 'Кафе «Уют» & Co')

    def test_short_name_is_bounded(self):
        data = json.loads(manifest('Очень длинное название магазина', 'index.html',
                                   '#000', '#fff'))
        self.assertLessEqual(len(data['short_name']), 12)

    def test_icon_uses_first_letter(self):
        from projects.pwa import icon_svg

        svg = icon_svg('Магазин', '#fff', '#000')
        self.assertIn('>М<', svg)

    def test_empty_name_falls_back(self):
        from projects.pwa import icon_svg

        self.assertIn('>A<', icon_svg('   ', '#fff', '#000'))

    def test_service_worker_has_no_external_links(self):
        worker = service_worker(1, ['index.html'])
        self.assertNotIn('https://', worker)
        self.assertNotIn('http://', worker)


class PwaEndpointTests(PwaPackageTests):
    def test_export_header_reports_pwa(self):
        client = self.client_for()

        plain = client.get(f'/api/projects/{self.project.id}/export/')
        self.assertEqual(plain['X-AuraBuilder-PWA'], '0')

        with_pwa = client.get(f'/api/projects/{self.project.id}/export/?pwa=1')
        self.assertEqual(with_pwa['X-AuraBuilder-PWA'], '1')

    def test_export_contains_pwa_files(self):
        import io
        import zipfile

        client = self.client_for()
        response = client.get(f'/api/projects/{self.project.id}/export/?pwa=1')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
        self.assertIn('service-worker.js', names)
        self.assertIn('manifest.json', names)
        self.assertIn('assets/icons/icon.svg', names)