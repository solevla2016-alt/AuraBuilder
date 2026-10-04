"""Права доступа по ролям (ТЗ п.11.1).

Проверяется матрица целиком: каждый роль против каждого действия. Если
матрица расширится новым действием, тест напомнит, какие роли его
получили и какие — нет, а не оставит вопрос на ревью.

Отдельно проверяются правила, которые не видны в матрице:

* неизвестная роль не даёт прав;
* анонимный пользователь не проходит;
* чужой проект отвечает 404, а не 403 — иначе по коду ответа можно
  перебором узнать, какие проекты существуют;
* список проектов показывает только доступные;
* каталог модулей остаётся публичным.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog, Membership, Role, UserConsent
from accounts.permissions import (
    DELETE,
    EDIT_CONTENT,
    EDIT_SETTINGS,
    MANAGE_ACCESS,
    MANAGE_BILLING,
    MANAGE_INTEGRATIONS,
    PUBLISH,
    VIEW,
    actions_for,
    can,
)
from projects.models import Project, default_tree

User = get_user_model()


def make_project(owner, name='Проект'):
    return Project.objects.create(name=name, tree=default_tree(), owner=owner)


class RoleMatrixTests(APITestCase):
    """Матрица ролей из ТЗ п.11.1."""

    def setUp(self):
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'verysecret123')
        self.project = make_project(self.owner)

    def _role_user(self, role):
        user = User.objects.create_user(
            f'user-{role}', f'{role}@example.com', 'verysecret123'
        )
        Membership.objects.create(project=self.project, user=user, role=role)
        return user

    def test_owner_has_all_actions(self):
        expected = {
            VIEW,
            EDIT_CONTENT,
            EDIT_SETTINGS,
            PUBLISH,
            MANAGE_INTEGRATIONS,
            MANAGE_BILLING,
            DELETE,
            MANAGE_ACCESS,
        }
        self.assertEqual(actions_for(Role.OWNER), frozenset(expected))

    def test_viewer_only_reads(self):
        user = self._role_user(Role.VIEWER)
        self.assertTrue(can(user, self.project, VIEW))
        for action in (EDIT_CONTENT, EDIT_SETTINGS, PUBLISH, DELETE, MANAGE_ACCESS):
            self.assertFalse(can(user, self.project, action), action)

    def test_editor_changes_content_but_not_settings(self):
        user = self._role_user(Role.EDITOR)
        self.assertTrue(can(user, self.project, EDIT_CONTENT))
        self.assertFalse(can(user, self.project, EDIT_SETTINGS))
        self.assertFalse(can(user, self.project, PUBLISH))
        self.assertFalse(can(user, self.project, DELETE))

    def test_dev_manages_integrations_without_publishing(self):
        user = self._role_user(Role.DEV)
        self.assertTrue(can(user, self.project, MANAGE_INTEGRATIONS))
        self.assertTrue(can(user, self.project, EDIT_CONTENT))
        self.assertFalse(can(user, self.project, PUBLISH))
        self.assertFalse(can(user, self.project, MANAGE_BILLING))

    def test_admin_publishes_but_cannot_delete(self):
        user = self._role_user(Role.ADMIN)
        self.assertTrue(can(user, self.project, PUBLISH))
        self.assertTrue(can(user, self.project, EDIT_SETTINGS))
        self.assertFalse(can(user, self.project, DELETE))

    def test_unknown_role_has_no_rights(self):
        user = User.objects.create_user('stranger', 's@example.com', 'verysecret123')
        Membership.objects.create(project=self.project, user=user, role='root')
        for action in (VIEW, EDIT_CONTENT, DELETE):
            self.assertFalse(can(user, self.project, action), action)

    def test_no_membership_no_rights(self):
        user = User.objects.create_user('other', 'other@example.com', 'verysecret123')
        self.assertFalse(can(user, self.project, VIEW))

    def test_anonymous_has_no_rights(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(can(AnonymousUser(), self.project, VIEW))


@override_settings(ROOT_URLCONF='controlplane.urls')
class ApiTestCase(APITestCase):
    """Общая база для проверок через API.

    Лимит входа поднят, а кеш очищается: в тестах один и тот же адрес
    входит десятки раз за минуту, иначе проверки прав упирались бы в
    антиперебор (он проверяется отдельно, в LoginThrottleTests).
    """

    def setUp(self):
        cache.clear()

    def login_as(self, user, password='verysecret123'):
        response = self.client.post(
            '/api/auth/login/', {'login': user.username, 'password': password}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        return response


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class ProjectAccessApiTests(ApiTestCase):
    """Права через API: то, что видит реальный клиент."""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'verysecret123')
        self.project = make_project(self.owner)

        self.viewer = User.objects.create_user('viewer', 'v@example.com', 'verysecret123')
        Membership.objects.create(
            project=self.project, user=self.viewer, role=Role.VIEWER
        )

        self.editor = User.objects.create_user('editor', 'e@example.com', 'verysecret123')
        Membership.objects.create(
            project=self.project, user=self.editor, role=Role.EDITOR
        )

        self.outsider = User.objects.create_user('outsider', 'o@example.com', 'verysecret123')
        self.other_project = make_project(self.outsider, 'Чужой')

    def _login(self, user):
        return self.login_as(user)

    def test_login_returns_tokens_and_user(self):
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'owner', 'password': 'verysecret123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['user']['username'], 'owner')
        # Пароль не должен утекать в ответ.
        self.assertNotIn('password', str(response.data))

    def test_login_by_email(self):
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'owner@example.com', 'password': 'verysecret123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_wrong_password(self):
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'owner', 'password': 'wrong-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Текст не должен отличаться для несуществующего логина:
        # иначе по сообщению видно, какие логины есть.
        other = self.client.post(
            '/api/auth/login/',
            {'login': 'no-such-user', 'password': 'wrong-password'},
            format='json',
        )
        self.assertEqual(str(response.data), str(other.data))

    def test_projects_list_requires_auth(self):
        response = self.client.get('/api/projects/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_shows_only_accessible_projects(self):
        self._login(self.owner)
        body = self.client.get('/api/projects/').json()
        ids = {p['id'] for p in body}
        self.assertIn(str(self.project.id), ids)
        self.assertNotIn(str(self.other_project.id), ids)

    def test_outsider_gets_404_not_403(self):
        # 403 подтвердил бы, что проект существует. Ответ должен быть
        # одинаковым для несуществующего и для чужого.
        self._login(self.outsider)
        response = self.client.get(f'/api/projects/{self.project.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_viewer_can_read_but_not_write(self):
        self._login(self.viewer)
        url = f'/api/projects/{self.project.id}/'
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)

        response = self.client.patch(url, {'name': 'Переименовано'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'Проект')

    def test_editor_can_write(self):
        self._login(self.editor)
        response = self.client.patch(
            f'/api/projects/{self.project.id}/', {'name': 'Переименовано'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'Переименовано')

    def test_editor_cannot_delete(self):
        self._login(self.editor)
        response = self.client.delete(f'/api/projects/{self.project.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Project.objects.filter(pk=self.project.id).exists())

    def test_owner_can_delete(self):
        self._login(self.owner)
        response = self.client.delete(f'/api/projects/{self.project.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Project.objects.filter(pk=self.project.id).exists())

    def test_created_project_belongs_to_creator(self):
        self._login(self.editor)
        response = self.client.post(
            '/api/projects/', {'name': 'Новый'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = Project.objects.get(pk=response.data['id'])
        self.assertEqual(created.owner_id, self.editor.id)

    def test_module_catalog_stays_public(self):
        # Палитра нужна редактору раньше, чем токен, и не содержит
        # пользовательских данных.
        response = self.client.get('/api/modules/?stage=3')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total'], 27)

    def test_health_stays_public(self):
        self.assertEqual(self.client.get('/api/health/').status_code, status.HTTP_200_OK)

    def test_owner_always_has_rights_even_without_membership_row(self):
        # Владелец хранится в проекте, а не в таблице участников.
        # Удаление записи не должно оставить проект без управления.
        user = User.objects.create_user('boss', 'b@example.com', 'verysecret123')
        project = make_project(user, 'Без записи')
        self.assertTrue(can(user, project, DELETE))
        self.assertEqual(project_role_of(user, project), Role.OWNER)


def project_role_of(user, project):
    from accounts.permissions import project_role

    return project_role(user, project)


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class MemberManagementTests(ApiTestCase):
    """Выдача ролей участникам (ТЗ п.11.1: Owner — управление доступом)."""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'verysecret123')
        self.editor = User.objects.create_user('editor', 'e@example.com', 'verysecret123')
        self.project = make_project(self.owner)

    def _login(self, user):
        self.login_as(user)

    def test_owner_grants_role(self):
        self._login(self.owner)
        response = self.client.post(
            f'/api/projects/{self.project.id}/members/',
            {'login': 'editor', 'role': Role.EDITOR},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['role'], Role.EDITOR)

    def test_editor_cannot_grant_roles(self):
        Membership.objects.create(
            project=self.project, user=self.editor, role=Role.EDITOR
        )
        self._login(self.editor)
        response = self.client.post(
            f'/api/projects/{self.project.id}/members/',
            {'login': 'owner', 'role': Role.VIEWER},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_role_cannot_be_granted(self):
        self._login(self.owner)
        response = self.client.post(
            f'/api/projects/{self.project.id}/members/',
            {'login': 'editor', 'role': Role.OWNER},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_user_rejected(self):
        self._login(self.owner)
        response = self.client.post(
            f'/api/projects/{self.project.id}/members/',
            {'login': 'нет-такого', 'role': Role.VIEWER},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_members_list_includes_owner(self):
        Membership.objects.create(
            project=self.project, user=self.editor, role=Role.EDITOR
        )
        self._login(self.owner)
        body = self.client.get(f'/api/projects/{self.project.id}/members/').json()
        roles = {m['username']: m['role'] for m in body}
        self.assertEqual(roles['owner'], Role.OWNER)
        self.assertEqual(roles['editor'], Role.EDITOR)

    def test_role_change_does_not_duplicate(self):
        self._login(self.owner)
        url = f'/api/projects/{self.project.id}/members/'
        self.client.post(url, {'login': 'editor', 'role': Role.VIEWER}, format='json')
        response = self.client.post(url, {'login': 'editor', 'role': Role.EDITOR}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Membership.objects.filter(project=self.project).count(), 1)
        self.assertEqual(Membership.objects.get(project=self.project).role, Role.EDITOR)


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class AuditLogTests(ApiTestCase):
    """Журнал действий (ТЗ п.11.2): кто, когда, что, откуда."""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'verysecret123')
        self.project = make_project(self.owner)
        self.login_as(self.owner)

    def test_create_and_update_are_logged(self):
        created = self.client.post('/api/projects/', {'name': 'С логом'}, format='json')
        project_id = created.data['id']
        self.client.patch(
            f'/api/projects/{project_id}/', {'name': 'Переименован'}, format='json'
        )

        entries = AuditLog.objects.filter(project_id=project_id)
        actions = {e.action for e in entries}
        self.assertIn('project.create', actions)
        self.assertIn('project.update', actions)

    def test_log_keeps_ip_and_user_agent(self):
        self.client.patch(
            f'/api/projects/{self.project.id}/',
            {'name': 'Правка'},
            format='json',
            HTTP_USER_AGENT='Тестовый агент',
            HTTP_X_FORWARDED_FOR='203.0.113.7',
        )
        entry = AuditLog.objects.filter(action='project.update').first()
        self.assertEqual(entry.ip, '203.0.113.7')
        self.assertEqual(entry.user_agent, 'Тестовый агент')
        self.assertEqual(entry.actor_id, self.owner.id)

    def test_audit_endpoint_requires_project_access(self):
        outsider = User.objects.create_user('outsider', 'o@example.com', 'verysecret123')
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'outsider', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        response = self.client.get(f'/api/projects/{self.project.id}/audit/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class ConsentTests(ApiTestCase):
    """Согласие на обработку ПДн (ТЗ п.7.3, 152-ФЗ)."""

    def setUp(self):
        super().setUp()

    def test_registration_records_consent(self):
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'noviy',
                'email': 'noviy@example.com',
                'password': 'verysecret123',
                'consent_pdn': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='noviy')
        consent = UserConsent.objects.get(user=user)
        self.assertTrue(consent.active)
        self.assertIsNotNone(consent.ip)

    def test_registration_without_consent_rejected(self):
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'bez',
                'email': 'bez@example.com',
                'password': 'verysecret123',
                'consent_pdn': False,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('consent_pdn', str(response.data))
        self.assertFalse(User.objects.filter(username='bez').exists())

    def test_honeypot_rejects_bot(self):
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'bot',
                'email': 'bot@example.com',
                'password': 'verysecret123',
                'consent_pdn': True,
                'website': 'http://spam.example',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(username='bot').exists())

    def test_duplicate_username_rejected(self):
        User.objects.create_user('taken', 't@example.com', 'verysecret123')
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'TAKEN',
                'email': 'other@example.com',
                'password': 'verysecret123',
                'consent_pdn': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_consent_can_be_revoked(self):
        user = User.objects.create_user('user', 'u@example.com', 'verysecret123')
        UserConsent.objects.create(user=user)
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'user', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        self.assertEqual(self.client.get('/api/auth/consent/').status_code, 200)

        response = self.client.delete('/api/auth/consent/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(UserConsent.objects.get(user=user).revoked_at)


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class TokenLifecycleTests(ApiTestCase):
    """Время жизни токенов и отзыв (ТЗ п.7.7)."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('user', 'u@example.com', 'verysecret123')

    def _login(self):
        return self.client.post(
            '/api/auth/login/',
            {'login': 'user', 'password': 'verysecret123'},
            format='json',
        )

    def test_refresh_rotates_token(self):
        login = self._login()
        old_refresh = login.data['refresh']

        first = self.client.post(
            '/api/auth/refresh/', {'refresh': old_refresh}, format='json'
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIn('access', first.data)

        # Старый refresh после ротации не работает: повторное
        # использование означает кражу токена.
        second = self.client.post(
            '/api/auth/refresh/', {'refresh': old_refresh}, format='json'
        )
        self.assertEqual(second.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_revokes_refresh(self):
        login = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        response = self.client.post(
            '/api/auth/logout/', {'refresh': login.data['refresh']}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        after = self.client.post(
            '/api/auth/refresh/', {'refresh': login.data['refresh']}, format='json'
        )
        self.assertEqual(after.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_token(self):
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)
        login = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'user')

    def test_bad_token_rejected(self):
        # Значение намеренно латиницей: заголовок HTTP не поддерживает
        # не-ASCII, и подделка токена с кириллицей невозможна.
        self.client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-token')
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)


class PasswordHashingTests(APITestCase):  # без входа, лимит не нужен
    """Argon2id (ТЗ п.7.3)."""

    def test_password_is_hashed_with_argon2(self):
        from django.contrib.auth.hashers import identify_hasher

        user = User.objects.create_user('h', 'h@example.com', 'verysecret123')
        self.assertTrue(user.password.startswith('argon2'))
        self.assertEqual(identify_hasher(user.password).algorithm, 'argon2')

    def test_raw_password_not_stored(self):
        user = User.objects.create_user('h2', 'h2@example.com', 'verysecret123')
        self.assertNotIn('verysecret123', user.password)
        self.assertTrue(user.check_password('verysecret123'))

class LoginThrottleTests(ApiTestCase):
    """Антиперебор паролей: 5 попыток за 10 минут (ТЗ п.7.7).

    Проверяется с настоящими значениями настроек, а не с поднятым
    лимитом: если формат лимита снова сломается при разборе, тест
    упадёт здесь, а не в самый неподходящий момент.
    """

    def setUp(self):
        super().setUp()
        User.objects.create_user('target', 'target@example.com', 'verysecret123')

    def test_sixth_attempt_is_blocked(self):
        statuses = []
        for _ in range(6):
            response = self.client.post(
                '/api/auth/login/',
                {'login': 'target', 'password': 'wrong'},
                format='json',
            )
            statuses.append(response.status_code)

        self.assertEqual(statuses[:5], [400] * 5)
        self.assertEqual(
            statuses[5],
            status.HTTP_429_TOO_MANY_REQUESTS,
            f'шестая попытка не заблокирована: {statuses}',
        )

    def test_correct_password_blocked_after_five_failures(self):
        for _ in range(5):
            self.client.post(
                '/api/auth/login/',
                {'login': 'target', 'password': 'wrong'},
                format='json',
            )
        # Правильный пароль тоже не проходит: иначе счётчик можно
        # было бы обнулить, перебрав пять неверных.
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'target', 'password': 'verysecret123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_window_is_shared_by_registration(self):
        for _ in range(5):
            self.client.post(
                '/api/auth/register/',
                {
                    'username': 'bot',
                    'email': 'bot@example.com',
                    'password': 'verysecret123',
                    'consent_pdn': True,
                },
                format='json',
            )
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'bot2',
                'email': 'bot2@example.com',
                'password': 'verysecret123',
                'consent_pdn': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
