"""Ревью-режим: замечания и согласование до публикации (этап 2).

Проверяется то, ради чего режим существует: замечание может оставить
даже Viewer, согласовать может только публикующий, а публикация не
проходит, пока проект или страница ждут решения. Отдельно — что
комментарии не попадают в архив: пакет должен работать без платформы.
"""

import io
import tempfile
import zipfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership
from accounts.permissions import Role
from billing.models import Subscription
from projects.models import (
    REVIEW_APPROVED,
    REVIEW_CHANGES,
    REVIEW_DRAFT,
    REVIEW_PENDING,
    Comment,
    Page,
    Project,
    default_tree,
)
from projects.versions import snapshot

User = get_user_model()


class ReviewApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(
            PUBLISH_ROOT=Path(self.tmp.name), PUBLICATION_BASE_URL='',
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

        self.owner = User.objects.create_user(
            'owner', 'owner@example.com', 'owner-pass-123',
        )
        Subscription.objects.create(user=self.owner, plan='start')
        self.project = Project.objects.create(
            name='Сайт студии', tree=default_tree(), owner=self.owner,
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
        )
        self.version = snapshot(
            self.project, self.project.tree, author=self.owner,
        )
        self.project.version = self.version.number
        self.project.save(update_fields=['version'])

        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token("owner", "owner-pass-123")}',
        )
        self.review_url = f'/api/projects/{self.project.id}/review/'
        self.comments_url = f'/api/projects/{self.project.id}/comments/'
        self.publish_url = f'/api/projects/{self.project.id}/site/'
        self.schedule_url = f'/api/projects/{self.project.id}/site/schedule/'

    def _token(self, login: str, password: str) -> str:
        response = self.client.post(
            '/api/auth/login/', {'login': login, 'password': password},
            format='json',
        )
        return response.data['access']

    def _client(self, username: str, role: str, password: str = 'member-pass'):
        user = User.objects.create_user(username, password=password)
        Membership.objects.create(project=self.project, user=user, role=role)
        client = self.client_class()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token(username, password)}',
        )
        return client

    def _comment(self, client=None, **payload):
        client = client or self.client
        payload.setdefault('text', 'Поправьте заголовок')
        return client.post(self.comments_url, payload, format='json')

    def _request_review(self, page=None):
        body = {'action': 'request'}
        if page is not None:
            body['page'] = str(page.id)
        return self.client.post(self.review_url, body, format='json')

    def _approve(self, page=None):
        body = {'action': 'approve'}
        if page is not None:
            body['page'] = str(page.id)
        return self.client.post(self.review_url, body, format='json')

    # --- комментарии ----------------------------------------------------

    def test_viewer_comments_on_main_and_inner_page(self):
        viewer = self._client('viewer', Role.VIEWER)
        main = self._comment(viewer, blockId='b1')
        self.assertEqual(main.status_code, status.HTTP_201_CREATED, main.data)
        self.assertIsNone(main.data['page'])
        self.assertEqual(main.data['author'], 'viewer')

        inner = self._comment(viewer, page=str(self.page.id))
        self.assertEqual(inner.status_code, status.HTTP_201_CREATED, inner.data)
        self.assertEqual(inner.data['page'], str(self.page.id))

        listing = viewer.get(f'{self.comments_url}?page={self.page.id}')
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual([item['text'] for item in listing.data['comments']],
                         ['Поправьте заголовок'])

    def test_empty_comment_is_refused(self):
        response = self._comment(text='   ')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_comment_on_foreign_page_is_refused(self):
        other = Project.objects.create(name='Чужой', owner=self.owner)
        foreign = Page.objects.create(project=other, title='Чужая', slug='x')
        response = self._comment(page=str(foreign.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_comment_can_be_closed_by_author_and_not_by_stranger(self):
        viewer = self._client('viewer', Role.VIEWER)
        created = self._comment(viewer).data
        url = f'{self.comments_url}{created["id"]}/'

        stranger = self._client('stranger', Role.EDITOR)
        denied = stranger.patch(url, {'resolved': True}, format='json')
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        closed = viewer.patch(url, {'resolved': True}, format='json')
        self.assertEqual(closed.status_code, status.HTTP_200_OK, closed.data)
        self.assertTrue(closed.data['resolved'])
        self.assertEqual(closed.data['resolvedBy'], 'viewer')

    def test_publisher_can_remove_foreign_comment(self):
        viewer = self._client('viewer', Role.VIEWER)
        created = self._comment(viewer).data
        response = self.client.delete(f'{self.comments_url}{created["id"]}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Comment.objects.filter(pk=created['id']).exists())

    # --- статусы --------------------------------------------------------

    def test_request_and_approve_project(self):
        started = self._request_review()
        self.assertEqual(started.status_code, status.HTTP_200_OK, started.data)
        self.assertEqual(started.data['status'], REVIEW_PENDING)

        approved = self._approve()
        self.assertEqual(approved.status_code, status.HTTP_200_OK, approved.data)
        self.assertEqual(approved.data['status'], REVIEW_APPROVED)
        self.assertEqual(approved.data['approvedBy'], 'owner')
        self.project.refresh_from_db()
        self.assertIsNotNone(self.project.review_approved_at)

    def test_viewer_cannot_request_or_approve(self):
        viewer = self._client('viewer', Role.VIEWER)
        request = viewer.post(
            self.review_url, {'action': 'request'}, format='json',
        )
        self.assertEqual(request.status_code, status.HTTP_403_FORBIDDEN)

        approve = viewer.post(
            self.review_url, {'action': 'approve'}, format='json',
        )
        self.assertEqual(approve.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_requests_and_admin_approves_page(self):
        editor = self._client('editor', Role.EDITOR)
        admin = self._client('admin', Role.ADMIN)

        requested = editor.post(
            self.review_url,
            {'action': 'request', 'page': str(self.page.id)},
            format='json',
        )
        self.assertEqual(requested.status_code, status.HTTP_200_OK, requested.data)
        self.assertEqual(requested.data['pages'][0]['status'], REVIEW_PENDING)

        # Редактор не публикует, поэтому и согласовать не может.
        denied = editor.post(
            self.review_url,
            {'action': 'approve', 'page': str(self.page.id)},
            format='json',
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        approved = admin.post(
            self.review_url,
            {'action': 'approve', 'page': str(self.page.id)},
            format='json',
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK, approved.data)
        self.assertEqual(approved.data['pages'][0]['status'], REVIEW_APPROVED)
        self.assertEqual(approved.data['pages'][0]['approvedBy'], 'admin')
        self.page.refresh_from_db()
        self.assertEqual(self.page.review_status, REVIEW_APPROVED)

    def test_approve_requires_pending_or_changes(self):
        response = self._approve()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_new_comment_after_approval_returns_changes(self):
        self._request_review(page=self.page)
        self._approve(page=self.page)
        self.page.refresh_from_db()
        self.assertEqual(self.page.review_status, REVIEW_APPROVED)

        self._comment(page=str(self.page.id))
        self.page.refresh_from_db()
        self.assertEqual(self.page.review_status, REVIEW_CHANGES)
        self.assertIsNone(self.page.review_approved_by)

    def test_tree_change_resets_approved_project(self):
        self._request_review()
        self._approve()
        tree = default_tree()
        tree['blocks'] = tree['blocks'][:1]
        response = self.client.put(
            f'/api/projects/{self.project.id}/',
            {
                'name': self.project.name,
                'tree': tree,
                'expectedVersion': self.project.version,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['reviewStatus'], REVIEW_DRAFT)

    def test_page_tree_change_resets_approved_page(self):
        self._request_review(page=self.page)
        self._approve(page=self.page)
        response = self.client.patch(
            f'/api/projects/{self.project.id}/pages/{self.page.id}/',
            {'tree': {'width': 720, 'blocks': []}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['reviewStatus'], REVIEW_DRAFT)

    # --- публикация -----------------------------------------------------

    def test_publication_is_blocked_while_review_pending(self):
        self._request_review()
        response = self.client.post(self.publish_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT,
                         response.data)
        self.assertEqual(response.data['review']['scope'], 'project')

    def test_page_changes_block_publication(self):
        self._request_review(page=self.page)
        self.client.post(
            self.review_url,
            {'action': 'changes', 'page': str(self.page.id)},
            format='json',
        )
        response = self.client.post(self.publish_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['review']['scope'], 'page')

    def test_force_review_publishes_and_is_recorded(self):
        self._request_review()
        response = self.client.post(
            self.publish_url, {'forceReview': True}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         response.data)
        self.project.refresh_from_db()
        self.assertTrue(
            self.project.events.filter(kind='review').exists(),
        )

    def test_schedule_is_blocked_while_review_pending(self):
        self._request_review()
        response = self.client.post(
            self.schedule_url,
            {'at': '2099-01-01T10:00:00Z'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT,
                         response.data)

    # --- экспорт --------------------------------------------------------

    def test_comments_are_not_in_exported_package(self):
        self._comment(text='Секретное замечание ревьюера')
        response = self.client.get(
            f'/api/projects/{self.project.id}/export/',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        for name in archive.namelist():
            self.assertNotIn('comment', name)
            self.assertNotIn(
                'Секретное замечание'.encode(),
                archive.read(name),
            )
