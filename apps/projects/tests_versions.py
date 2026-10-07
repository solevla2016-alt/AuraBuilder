"""Версии документа и конкурентное сохранение (ТЗ п.3.2).

Проверяется то, что отличает версии от обычного бэкапа: нумерация,
неизменяемость снимка, восстановление как новая версия и отказ при
расхождении версий. Модель командной работы в ТЗ описана как
optimistic concurrency (docs/TZ-GAPS.md, п.2.3), и именно он
реализован.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership, Role
from projects.models import DocumentVersion, Project, default_tree
from projects.versions import MAX_VERSIONS

User = get_user_model()


def tree_with(text: str) -> dict:
    tree = default_tree()
    tree['blocks'][1]['label'] = text
    return tree


class VersionsTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('tester', 'tester@example.com', 'verysecret123')
        self.project = Project.objects.create(
            name='Сайт', tree=default_tree(), owner=self.user
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'tester', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def url(self, suffix: str = '') -> str:
        return f'/api/projects/{self.project.id}/versions/{suffix}'

    def save(self, tree, **extra):
        return self.client.patch(
            f'/api/projects/{self.project.id}/', {'tree': tree, **extra}, format='json'
        )


class SnapshotTests(VersionsTestCase):
    def test_save_creates_version(self):
        response = self.save(tree_with('Первый'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['version'], 2)
        self.assertEqual(DocumentVersion.objects.count(), 1)
        version = DocumentVersion.objects.get()
        self.assertEqual(version.number, 2)
        self.assertEqual(version.tree['blocks'][1]['label'], 'Первый')
        self.assertEqual(version.author, self.user)

    def test_version_serialized_to_client(self):
        # Клиенту нужен номер версии: он предъявляет его при следующем
        # сохранении, и без него проверка конфликта не работает.
        self.save(tree_with('Первый'))
        self.project.refresh_from_db()
        body = self.client.get(f'/api/projects/{self.project.id}/').json()
        self.assertEqual(body['version'], 2)

    def test_unchanged_tree_creates_no_version(self):
        # Иначе каждый заход на страницу засорял бы историю
        # одинаковыми версиями и восстанавливать было бы нечего.
        self.assertEqual(self.save(default_tree()).status_code, 200)
        self.assertEqual(DocumentVersion.objects.count(), 0)
        self.assertEqual(self.save(default_tree()).status_code, 200)
        self.assertEqual(DocumentVersion.objects.count(), 0)

    def test_version_name_only_save_makes_no_version(self):
        self.client.patch(
            f'/api/projects/{self.project.id}/', {'name': 'Другое имя'}, format='json'
        )
        self.assertEqual(DocumentVersion.objects.count(), 0)

    def test_versions_are_pruned(self):
        for i in range(MAX_VERSIONS + 5):
            self.save(tree_with(f'Правка {i}'))
        kept = DocumentVersion.objects.filter(project=self.project)
        self.assertEqual(kept.count(), MAX_VERSIONS)
        # Обрезаются самые старые, а не новые: восстанавливать полезно
        # из недавнего.
        newest = kept.order_by('-number').first()
        self.assertEqual(newest.tree['blocks'][1]['label'], f'Правка {MAX_VERSIONS + 4}')


class ConcurrencyTests(VersionsTestCase):
    def test_matching_version_saves(self):
        self.save(tree_with('Первый'))
        self.project.refresh_from_db()
        response = self.save(tree_with('Второй'), expectedVersion=self.project.version)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['version'], 3)

    def test_stale_version_conflicts(self):
        self.save(tree_with('Первое'))
        self.project.refresh_from_db()
        current = self.project.version
        # Вторая вкладка получила ту же версию и держит её открытой.
        self.save(tree_with('Второе'))
        self.project.refresh_from_db()
        self.assertEqual(self.project.version, current + 1)

        stale = self.save(tree_with('Третье'), expectedVersion=current)
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(stale.data['version'], current + 1)
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.tree['blocks'][1]['label'], 'Третье')

    def test_no_conflict_without_expected_version(self):
        # Клиент без версии (старый редактор или скрипт) сохраняется как
        # раньше: требование версии не должно ломать тех, кто её не
        # присылает.
        self.save(tree_with('Первый'))
        response = self.save(tree_with('Второе'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_bad_expected_version_rejected(self):
        response = self.save(tree_with('Правка'), expectedVersion='не число')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class VersionListTests(VersionsTestCase):
    def test_empty_history_returns_current_version(self):
        body = self.client.get(self.url()).json()
        self.assertEqual(body['versions'], [])
        self.assertEqual(body['version'], 1)

    def test_list_has_rows_without_trees(self):
        self.save(tree_with('Первый'))
        body = self.client.get(self.url()).json()
        row = body['versions'][0]
        self.assertEqual(row['number'], 2)
        self.assertEqual(row['author'], 'tester')
        self.assertEqual(row['blocks'], 4)
        # Дерево не отдаётся списком: история растёт, а редактору нужны
        # строки. Полное дерево запрашивается для одной версии.
        self.assertNotIn('tree', row)

    def test_detail_includes_tree(self):
        self.save(tree_with('Первый'))
        body = self.client.get(self.url('2/')).json()
        self.assertEqual(body['tree']['blocks'][1]['label'], 'Первый')

    def test_missing_version_404(self):
        self.assertEqual(self.client.get(self.url('99/')).status_code, 404)


class ManualSnapshotTests(VersionsTestCase):
    def test_manual_snapshot_with_label(self):
        response = self.client.post(self.url(), {'label': 'Перед редизайном'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['label'], 'Перед редизайном')
        self.assertEqual(DocumentVersion.objects.count(), 1)

    def test_manual_snapshot_survives_later_edits(self):
        self.client.post(self.url(), {'label': 'До'}, format='json')
        self.save(tree_with('После'))
        self.assertEqual(DocumentVersion.objects.count(), 2)
        self.assertEqual(DocumentVersion.objects.first().tree['blocks'][1]['label'], 'После')


class RestoreTests(VersionsTestCase):
    def test_restore_brings_back_old_tree(self):
        self.save(tree_with('Первое'))
        self.save(tree_with('Второе'))
        response = self.client.post(self.url('2/restore/'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.project.refresh_from_db()
        self.assertEqual(self.project.tree['blocks'][1]['label'], 'Первое')

    def test_restore_is_itself_a_version(self):
        # Иначе «отменить восстановление» было бы нечем: переписать
        # историю нельзя, добавлять можно.
        self.save(tree_with('Первое'))
        self.save(tree_with('Второе'))
        self.client.post(self.url('2/restore/'))
        numbers = list(
            DocumentVersion.objects.filter(project=self.project)
            .order_by('number')
            .values_list('number', 'label')
        )
        self.assertEqual([n for n, _ in numbers], [2, 3, 4])
        self.assertIn('Восстановлено из версии 2', numbers[-1][1])

    def test_restore_bumps_project_version(self):
        self.save(tree_with('Первое'))
        self.client.post(self.url('2/restore/'))
        self.project.refresh_from_db()
        self.assertEqual(self.project.version, 3)

    def test_restore_missing_version_404(self):
        self.assertEqual(self.client.post(self.url('99/restore/')).status_code, 404)


class VersionAccessTests(VersionsTestCase):
    """Права на историю документа (ТЗ п.11.1)."""

    def setUp(self):
        super().setUp()
        self.viewer = User.objects.create_user('viewer', 'v@example.com', 'verysecret123')
        Membership.objects.create(project=self.project, user=self.viewer, role=Role.VIEWER)
        self.outsider = User.objects.create_user('outsider', 'o@example.com', 'verysecret123')

    def _login(self, user):
        response = self.client.post(
            '/api/auth/login/',
            {'login': user.username, 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def test_viewer_reads_history_but_cannot_snapshot(self):
        self.save(tree_with('Первое'))
        self._login(self.viewer)
        body = self.client.get(self.url())
        self.assertEqual(body.status_code, status.HTTP_200_OK)
        self.assertEqual(len(body.data['versions']), 1)
        response = self.client.post(self.url(), {'label': 'Своя'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_restore(self):
        self.save(tree_with('Первое'))
        self._login(self.viewer)
        response = self.client.post(self.url('2/restore/'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.project.refresh_from_db()
        self.assertEqual(self.project.tree['blocks'][1]['label'], 'Первое')

    def test_outsider_gets_404(self):
        self._login(self.outsider)
        self.assertEqual(self.client.get(self.url()).status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_rejected(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url()).status_code, status.HTTP_401_UNAUTHORIZED)