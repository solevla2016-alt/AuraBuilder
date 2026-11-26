"""Скачивание архивов по короткоживущей ссылке.

Проверяется главное, что сломалось в интерфейсе: переход браузера без
заголовка Authorization. Раньше такие ссылки отвечали 401, и «Скачать
архив» не работал ни в одном браузере, хотя API с токеном отдавал файл.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import Subscription
from projects.models import DocumentVersion, Project, default_tree

User = get_user_model()


class DownloadTicketTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'downloader', 'downloader@example.com', 'verysecret123',
        )
        Subscription.objects.create(user=self.user, plan='start')
        self.project = Project.objects.create(
            name='Магазин цветов',
            tree=default_tree(),
            owner=self.user,
            version=1,
        )
        # Экспорт отдаёт последний снимок, а не текущее дерево: без
        # версии он честно отвечает 409 «сначала сохраните проект».
        DocumentVersion.objects.create(
            project=self.project,
            number=1,
            tree=self.project.tree,
            author=self.user,
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'downloader', 'password': 'verysecret123'},
            format='json',
        )
        self.access = response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access}')
        self.export_path = f'/api/projects/{self.project.id}/export/'
        self.config_path = f'/api/projects/{self.project.id}/config/'

    def issue(self, path: str) -> str:
        response = self.client.post(
            '/api/auth/download-ticket/',
            {'path': path},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data['ticket']

    def test_ticket_opens_export_without_authorization_header(self):
        ticket = self.issue(self.export_path)
        # Именно так ходит браузер по <a href>: без заголовка.
        self.client.credentials()
        response = self.client.get(self.export_path, {'ticket': ticket})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/zip')

    def test_ticket_opens_config_backup(self):
        ticket = self.issue(self.config_path)
        self.client.credentials()
        response = self.client.get(self.config_path, {'ticket': ticket})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('application/json', response['Content-Type'])

    def test_ticket_is_bound_to_one_path(self):
        ticket = self.issue(self.export_path)
        self.client.credentials()
        response = self.client.get(self.config_path, {'ticket': ticket})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ticket_is_not_issued_for_other_endpoints(self):
        response = self.client.post(
            '/api/auth/download-ticket/',
            {'path': '/api/auth/me/'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ticket_requires_authentication_to_issue(self):
        self.client.credentials()
        response = self.client.post(
            '/api/auth/download-ticket/',
            {'path': self.export_path},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_ticket_is_rejected(self):
        ticket = self.issue(self.export_path)
        self.client.credentials()
        # Отрицательный срок: любой возраст подписи уже «больше» него,
        # поэтому ждать две минуты в тесте не нужно.
        with patch('accounts.downloads.TICKET_TTL_SECONDS', -1):
            response = self.client.get(self.export_path, {'ticket': ticket})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ticket_does_not_authorize_writes(self):
        ticket = self.issue(self.export_path)
        self.client.credentials()
        response = self.client.post(
            f'/api/projects/{self.project.id}/members/',
            {'username': 'downloader', 'role': 'viewer'},
            format='json',
            QUERY_STRING=f'ticket={ticket}',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
