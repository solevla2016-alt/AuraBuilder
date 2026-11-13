"""Аналитика опубликованного сайта и приём заявок.

Проверяется то, ради чего счётчики поставлены: просмотр страницы
отличается от загрузки картинки, робот не считается читателем, источник
перехода не подменяется, а заявка не теряется и не пишется в чужой
проект. Отдельно — что чужой человек не видит ни статистику, ни
заявки.
"""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Membership, Role
from projects.models import Project
from publications.models import Site, SiteVersion
from publications.service import publish_root

from .forms import MAX_FORM_BYTES
from .models import FormSubmission, PageView, TrafficSource

User = get_user_model()


@override_settings(
    LOGIN_ATTEMPT_LIMIT=1000,
    PUBLICATION_BASE_URL='',
    FORM_THROTTLE_RATE='1000/min',
)
class SiteBase(TestCase):
    """Опубликованный сайт без полной сборки пакета.

    Файлы кладутся руками: проверяется раздача и счётчики, а сборка
    пакета уже покрыта тестами публикации. Так тест не зависит от
    вёрстки блоков и работает быстро.
    """

    def setUp(self):
        cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(PUBLISH_ROOT=Path(self.tmp.name))
        self.override.enable()
        self.addCleanup(self.override.disable)

        # Форма шлёт JSON: обычный клиент Django здесь отправил бы
        # multipart и получил бы 415 — это поведение реального
        # скомпилированного скрипта, а не тестового клиента.
        self.form_client = APIClient()

        self.owner = User.objects.create_user('owner', password='pass-owner')
        self.project = Project.objects.create(owner=self.owner, name='Цветы')
        self.site = Site.objects.create(project=self.project, slug='shop')

        directory = publish_root() / 'sites' / 'shop' / 'v1'
        (directory / 'about').mkdir(parents=True)
        (directory / 'index.html').write_text('<h1>Главная</h1>', encoding='utf-8')
        (directory / 'about' / 'index.html').write_text('<h1>О нас</h1>', encoding='utf-8')
        (directory / 'style.css').write_text('body{}', encoding='utf-8')

        self.version = SiteVersion.objects.create(
            site=self.site, number=1, path='sites/shop/v1', files=3,
        )
        self.site.current_version = self.version
        self.site.save(update_fields=['current_version'])

    def client_for(self, user, password: str) -> APIClient:
        client = APIClient()
        response = client.post(
            '/api/auth/login/',
            {'login': user.username, 'password': password},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}',
        )
        return client

    def visit(self, path: str = '/sites/shop/', **extra):
        response = self.client.get(path, **extra)
        self.assertEqual(response.status_code, 200)
        return response


class TrackingTests(SiteBase):
    def test_html_view_is_counted(self):
        self.visit()
        row = PageView.objects.get(site=self.site)
        self.assertEqual(row.path, '/')
        self.assertEqual(row.views, 1)
        self.assertEqual(TrafficSource.objects.get(site=self.site).source, 'direct')

    def test_repeat_views_add_up(self):
        self.visit()
        self.visit()
        self.assertEqual(PageView.objects.get(site=self.site).views, 2)

    def test_inner_page_has_its_own_path(self):
        self.visit('/sites/shop/about/')
        self.assertEqual(PageView.objects.get(site=self.site).path, '/about/')

    def test_asset_is_not_a_view(self):
        self.visit('/sites/shop/style.css')
        self.assertFalse(PageView.objects.exists())

    def test_bot_is_skipped(self):
        self.visit(HTTP_USER_AGENT='Mozilla/5.0 (compatible; YandexBot/3.0)')
        self.assertFalse(PageView.objects.exists())

    def test_utm_source_wins_over_referer(self):
        self.visit(
            '/sites/shop/?utm_source=VK',
            HTTP_REFERER='https://yandex.ru/search?text=flowers',
        )
        self.assertEqual(TrafficSource.objects.get(site=self.site).source, 'vk')

    def test_search_referer_is_grouped(self):
        self.visit(HTTP_REFERER='https://yandex.ru/search?text=flowers')
        self.assertEqual(TrafficSource.objects.get(site=self.site).source, 'search')

    def test_social_referer_is_grouped(self):
        self.visit(HTTP_REFERER='https://t.me/some_channel')
        self.assertEqual(TrafficSource.objects.get(site=self.site).source, 'social')

    def test_internal_transition_is_marked(self):
        self.visit(HTTP_REFERER='http://testserver/sites/shop/')
        self.assertEqual(TrafficSource.objects.get(site=self.site).source, 'internal')

    def test_unknown_referer_keeps_its_host(self):
        self.visit(HTTP_REFERER='https://blog.example.org/post')
        self.assertEqual(
            TrafficSource.objects.get(site=self.site).source, 'blog.example.org',
        )

    def test_unknown_page_is_not_served_and_not_counted(self):
        response = self.client.get('/sites/shop/missing/')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(PageView.objects.exists())

    def test_old_rows_are_pruned(self):
        old = timezone.localdate() - timedelta(days=500)
        PageView.objects.create(site=self.site, day=old, path='/', views=5)
        TrafficSource.objects.create(site=self.site, day=old, source='direct', views=5)
        self.visit()
        self.assertFalse(PageView.objects.filter(day=old).exists())
        self.assertFalse(TrafficSource.objects.filter(day=old).exists())


class SubmitFormTests(SiteBase):
    URL = '/api/forms/'

    def submit(self, data: dict, **extra):
        return self.form_client.post(
            self.URL, data, format='json',
            HTTP_REFERER='http://testserver/sites/shop/about/', **extra,
        )

    def test_submission_is_stored(self):
        response = self.submit({'name': 'Иван', 'phone': '+7 900 000-00-00'})
        self.assertEqual(response.status_code, 201, response.data)
        submission = FormSubmission.objects.get(site=self.site)
        self.assertEqual(submission.page, '/about/')
        self.assertEqual(submission.data['name'], 'Иван')
        self.assertEqual(submission.source, 'direct')

    def test_site_can_be_given_explicitly(self):
        response = self.form_client.post(
            self.URL, {'_site': 'shop', 'name': 'Пётр'}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(FormSubmission.objects.get(site=self.site).data['name'], 'Пётр')

    def test_plain_route_is_accepted(self):
        # Старые сборки шлют на /api/forms без косой черты.
        response = self.form_client.post(
            '/api/forms', {'_site': 'shop', 'name': 'Анна'}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_unknown_site_is_rejected(self):
        response = self.form_client.post(
            self.URL, {'name': 'Иван'}, format='json',
            HTTP_REFERER='http://testserver/sites/nope/',
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(FormSubmission.objects.exists())

    def test_withdrawn_site_is_rejected(self):
        self.site.state = 'withdrawn'
        self.site.save(update_fields=['state'])
        response = self.submit({'name': 'Иван'})
        self.assertEqual(response.status_code, 410)
        self.assertFalse(FormSubmission.objects.exists())

    def test_empty_submission_is_rejected(self):
        response = self.submit({'name': '   ', 'nested': {'a': 1}})
        self.assertEqual(response.status_code, 400)

    def test_non_object_payload_is_rejected(self):
        response = self.form_client.post(
            self.URL, ['Иван'], format='json',
            HTTP_REFERER='http://testserver/sites/shop/',
        )
        self.assertEqual(response.status_code, 400)

    def test_oversized_payload_is_rejected(self):
        response = self.form_client.post(
            self.URL, {'_site': 'shop', 'text': 'x' * (MAX_FORM_BYTES + 100)},
            format='json',
        )
        self.assertEqual(response.status_code, 413)

    def test_honeypot_returns_success_without_writing(self):
        response = self.submit({'_hp': 'заполнено роботом', 'name': 'Иван'})
        self.assertEqual(response.status_code, 201)
        self.assertFalse(FormSubmission.objects.exists())

    def test_utm_is_kept_as_source(self):
        response = self.form_client.post(
            self.URL, {'_site': 'shop', 'name': 'Иван'}, format='json',
            HTTP_REFERER='http://testserver/sites/shop/?utm_source=newsletter',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            FormSubmission.objects.get(site=self.site).source, 'newsletter',
        )


class AnalyticsApiTests(SiteBase):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        PageView.objects.create(site=self.site, day=today, path='/', views=150)
        PageView.objects.create(site=self.site, day=today, path='/about/', views=50)
        TrafficSource.objects.create(
            site=self.site, day=today, source='search', views=120,
        )
        TrafficSource.objects.create(
            site=self.site, day=today, source='direct', views=80,
        )
        FormSubmission.objects.create(
            site=self.site, page='/', source='search',
            data={'name': 'Иван', 'phone': '+7'},
        )
        FormSubmission.objects.create(
            site=self.site, page='/about/', source='direct',
            data={'name': 'Пётр'},
        )

    def url(self, days: int | str = 7) -> str:
        return f'/api/projects/{self.project.id}/analytics/?days={days}'

    def test_owner_sees_totals_and_breakdown(self):
        response = self.client_for(self.owner, 'pass-owner').get(self.url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['totals']['views'], 200)
        self.assertEqual(response.data['totals']['submissions'], 2)
        self.assertEqual(response.data['totals']['conversion'], 1.0)
        self.assertEqual(response.data['site']['slug'], 'shop')
        self.assertEqual(len(response.data['series']), 7)
        self.assertEqual(response.data['sources'][0]['source'], 'search')
        self.assertEqual(response.data['pages'][0]['path'], '/')
        self.assertEqual(len(response.data['submissions']), 2)

    def test_period_changes_series_length(self):
        client = self.client_for(self.owner, 'pass-owner')
        response = client.get(self.url(30))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['series']), 30)

    def test_unknown_period_is_rejected(self):
        response = self.client_for(self.owner, 'pass-owner').get(self.url(8))
        self.assertEqual(response.status_code, 400)

    def test_outsider_does_not_see_analytics(self):
        stranger = User.objects.create_user('stranger', password='pass-x')
        response = self.client_for(stranger, 'pass-x').get(self.url())
        self.assertEqual(response.status_code, 404)

    def test_viewer_can_read(self):
        viewer = User.objects.create_user('viewer', password='pass-v')
        Membership.objects.create(
            project=self.project, user=viewer, role=Role.VIEWER,
        )
        response = self.client_for(viewer, 'pass-v').get(self.url())
        self.assertEqual(response.status_code, 200, response.data)

    def test_project_without_site_gets_empty_report(self):
        other = Project.objects.create(owner=self.owner, name='Без сайта')
        response = self.client_for(self.owner, 'pass-owner').get(
            f'/api/projects/{other.id}/analytics/',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['site'])
        self.assertEqual(response.data['totals']['views'], 0)

    def test_conversion_is_zero_without_views(self):
        PageView.objects.all().delete()
        FormSubmission.objects.all().delete()
        response = self.client_for(self.owner, 'pass-owner').get(self.url())
        self.assertEqual(response.data['totals']['conversion'], 0.0)
