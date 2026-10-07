"""Библиотека компонентов: стили, контраст, права.

ТЗ п.3.1: изменение стиля в библиотеке компонентов обновляет их на всех
страницах. Проверяется ровно то, что может испортить результат: чужой
цвет в палитре, нечитаемая пара «фон + текст», сброс к умолчаниям и
границы прав (ТЗ п.11.1).
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Membership, Role
from component_library.models import ComponentStyle, default_tokens
from projects.models import Project, default_tree

User = get_user_model()

STYLE_URL = '/api/projects/{project}/component-styles/{kind}/'
LIST_URL = '/api/projects/{project}/component-styles/'


class ComponentLibraryTestCase(APITestCase):
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
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def put_style(self, kind='section', tokens=None):
        return self.client.put(
            STYLE_URL.format(project=self.project.id, kind=kind),
            {'tokens': tokens if tokens is not None else {'background': 'panel'}},
            format='json',
        )


class StyleTests(ComponentLibraryTestCase):
    def test_list_returns_defaults_before_any_save(self):
        # Пустая библиотека должна отдавать фактические значения, а не
        # пустой список: иначе макет компонента рисовался бы вслепую.
        body = self.client.get(LIST_URL.format(project=self.project.id)).json()
        kinds = [s['kind'] for s in body['styles']]
        self.assertEqual(kinds, ['section', 'text', 'media'])
        section = body['styles'][0]
        self.assertEqual(section['tokens'], default_tokens('section'))
        self.assertTrue(section['isDefault'])

    def test_save_style_marks_it_as_custom(self):
        response = self.put_style(tokens={'background': 'canvas', 'text': 'textPrimary'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        body = self.client.get(LIST_URL.format(project=self.project.id)).json()
        section = next(s for s in body['styles'] if s['kind'] == 'section')
        self.assertEqual(section['tokens']['background'], 'canvas')
        self.assertFalse(section['isDefault'])
        self.assertIsNotNone(section['updatedAt'])

    def test_second_save_replaces_tokens(self):
        self.put_style(tokens={'background': 'canvas'})
        response = self.put_style(tokens={'background': 'panelRaised'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(ComponentStyle.objects.get(project=self.project).tokens['background'], 'panelRaised')

    def test_reset_returns_defaults(self):
        self.put_style(tokens={'background': 'canvas'})
        response = self.client.delete(STYLE_URL.format(project=self.project.id, kind='section'))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ComponentStyle.objects.count(), 0)
        body = self.client.get(LIST_URL.format(project=self.project.id)).json()
        section = next(s for s in body['styles'] if s['kind'] == 'section')
        self.assertTrue(section['isDefault'])
        self.assertEqual(section['tokens'], default_tokens('section'))

    def test_reset_without_style_is_not_an_error(self):
        # Кнопка «сбросить» наезжает на ещё не тронутый компонент.
        response = self.client.delete(STYLE_URL.format(project=self.project.id, kind='media'))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_unknown_kind_rejected(self):
        response = self.put_style(kind='widget', tokens={'background': 'canvas'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_style_of_another_project_not_visible(self):
        self.put_style(tokens={'background': 'canvas'})
        other = Project.objects.create(name='Другой', tree=default_tree(), owner=self.user)
        body = self.client.get(LIST_URL.format(project=other.id)).json()
        self.assertTrue(all(s['isDefault'] for s in body['styles']))

    def test_hex_color_allowed(self):
        response = self.put_style(
            tokens={'background': '#102A43', 'text': '#FFFFFF', 'radius': 4, 'padding': 12}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


class StyleValidationTests(ComponentLibraryTestCase):
    def test_unknown_token_name_rejected(self):
        response = self.put_style(tokens={'background': 'неЦвет'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_style_property_rejected(self):
        # Свойство не из списка — опечатка или попытка записать в стиль
        # то, что рендерер не умеет: молчаливый пропуск оставил бы
        # компонент «настроенным», но не изменившимся.
        response = self.put_style(tokens={'background': 'canvas', 'shadow': 'big'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_out_of_range_numbers_rejected(self):
        for tokens in (
            {'background': 'canvas', 'radius': 900},
            {'background': 'canvas', 'padding': -4},
            {'background': 'canvas', 'weight': 100},
            {'background': 'canvas', 'border': 40},
        ):
            response = self.put_style(tokens=tokens)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, tokens)

    def test_number_given_as_text_rejected(self):
        # «8» и 8 рисуются одинаково, но экспорт и сверка версий
        # сравнивают значения: молча принимать строку значило бы
        # сравнивать 8 с "8" и считать их разными.
        response = self.put_style(tokens={'background': 'canvas', 'radius': '8'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unreadable_pair_rejected(self):
        # Золото по песку — реальный дефект палитры (docs/TZ-GAPS.md,
        # п.4.10): контраст около 1.7:1, глазом в редакторе не виден.
        response = self.put_style(tokens={'background': 'accentSurface', 'text': 'accentText'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('онтраст', str(response.data))

    def test_readable_pair_accepted(self):
        response = self.put_style(tokens={'background': 'canvas', 'text': 'textPrimary'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_contrast_checked_in_both_themes(self):
        # Токен, читаемый в светлой теме и сливающийся в тёмной, должен
        # отклоняться: страницу смотрят в обеих.
        from projects.palette_tokens import THEMES

        readable_light = next(
            name
            for name in THEMES['light']
            if name in THEMES['dark']
            and _ratio(THEMES['light'][name], THEMES['light']['canvas']) >= 4.5
            and _ratio(THEMES['dark'][name], THEMES['dark']['canvas']) < 4.5
        )
        response = self.put_style(tokens={'background': 'canvas', 'text': readable_light})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_style_rejected(self):
        response = self.put_style(tokens={})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


def _ratio(first: str, second: str) -> float:
    from component_library.contrast import contrast_ratio

    return contrast_ratio(first, second)


class ComponentAccessTests(ComponentLibraryTestCase):
    """Права на библиотеку компонентов (ТЗ п.11.1)."""

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

    def test_viewer_reads_but_cannot_change(self):
        # Стили видны всем, кто видит проект: иначе редактор сообщил бы
        # «стиля нет» там, где он есть.
        self._login(self.viewer)
        body = self.client.get(LIST_URL.format(project=self.project.id))
        self.assertEqual(body.status_code, status.HTTP_200_OK)
        self.assertEqual(len(body.data['styles']), 3)
        self.assertEqual(self.put_style(tokens={'background': 'canvas'}).status_code, 403)

    def test_viewer_cannot_reset_style(self):
        self.put_style(tokens={'background': 'canvas'})
        self._login(self.viewer)
        response = self.client.delete(STYLE_URL.format(project=self.project.id, kind='section'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ComponentStyle.objects.count(), 1)

    def test_outsider_gets_404(self):
        self._login(self.outsider)
        self.assertEqual(
            self.client.get(LIST_URL.format(project=self.project.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_anonymous_rejected(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get(LIST_URL.format(project=self.project.id)).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )