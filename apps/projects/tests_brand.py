"""Брендбук и типограф.

Проверяется то, что видит заказчик: знаки в тексте, фирменный цвет и
шрифт, подпись внизу страницы и метки в ссылках. Отдельно — что
типограф не портит технические значения: адрес с «тире» внутри ломает
ссылку, и это заметно только у посетителя.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import Subscription
from projects.brand import (
    add_utm,
    brand_error,
    normalize_brand,
    on_accent,
    utm_params,
)
from projects.models import Project, default_tree
from projects.package import build_package
from projects.typography import TECHNICAL_PROPS, typograph, typograph_block

User = get_user_model()


class TypographTests(APITestCase):
    """Правила типографа и их безопасность для повторного прогона."""

    def test_quotes_become_guillemets(self):
        self.assertEqual(
            typograph('Он сказал "привет" и ушёл'),
            'Он сказал «привет» и\u00a0ушёл',
        )

    def test_odd_quotes_are_left_alone(self):
        # Нечётное число кавычек — почти наверняка апостроф или
        # незакрытая кавычка. Автоматическая расстановка сделала бы хуже.
        self.assertEqual(typograph('It"s fine'), 'It"s fine')

    def test_ellipsis_and_dashes(self):
        self.assertEqual(
            typograph('Ну... поехали - и всё'),
            'Ну… поехали\u00a0— и\u00a0всё',
        )

    def test_spaces_before_punctuation_are_removed(self):
        self.assertEqual(typograph('Привет , мир .'), 'Привет, мир.')

    def test_short_word_is_glued_to_next(self):
        # «в» в конце строки — признак черновика; неразрывный пробел
        # переносит слово целиком.
        self.assertEqual(typograph('идём в кино'), 'идём в\u00a0кино')

    def test_number_and_unit_are_glued(self):
        self.assertEqual(typograph('5 кг'), '5\u00a0кг')

    def test_repeat_run_changes_nothing(self):
        sample = 'Он сказал "привет"... через 5 минут - и ушёл в кино'
        once = typograph(sample)
        self.assertEqual(typograph(once), once)

    def test_technical_props_are_untouched(self):
        block = {
            'module': 'action.link',
            'props': {
                'link': 'https://example.com/a--b?x=1-2',
                'text': 'Текст -- с дефисами',
            },
        }
        fixed = typograph_block(block)
        self.assertEqual(fixed['props']['link'], 'https://example.com/a--b?x=1-2')
        self.assertEqual(fixed['props']['text'], 'Текст\u00a0— с\u00a0дефисами')

    def test_technical_list_is_not_empty(self):
        # Список — часть контракта: если его случайно очистят, типограф
        # начнёт править адреса и код, и сборка останется «успешной».
        self.assertIn('href', TECHNICAL_PROPS)
        self.assertIn('code', TECHNICAL_PROPS)

    def test_block_is_not_mutated(self):
        block = {'module': 'text.paragraph', 'content': 'Текст -- тут', 'props': {}}
        typograph_block(block)
        self.assertEqual(block['content'], 'Текст -- тут')


class BrandTests(APITestCase):
    def test_normalize_fills_defaults(self):
        brand = normalize_brand({'accent': '#aabbcc'})
        self.assertEqual(brand['accent'], '#AABBCC')
        self.assertEqual(brand['font'], 'sans')
        self.assertEqual(brand['signature'], '')

    def test_unknown_font_falls_back(self):
        self.assertEqual(normalize_brand({'font': 'comic'})['font'], 'sans')

    def test_accent_requires_hex(self):
        self.assertIsNotNone(brand_error({'accent': 'red'}))
        self.assertIsNone(brand_error({'accent': '#112233'}))

    def test_utm_characters_are_limited(self):
        self.assertIsNotNone(brand_error({'utmSource': 'моя кампания'}))
        self.assertIsNone(brand_error({'utmSource': 'моя_кампания'}))

    def test_unknown_field_is_rejected(self):
        self.assertIsNotNone(brand_error({'colour': '#112233'}))

    def test_on_accent_is_contrasting(self):
        self.assertEqual(on_accent('#111111'), '#FFFFFF')
        self.assertEqual(on_accent('#FFFFFF'), '#111827')

    def test_utm_params_skip_empty_values(self):
        params = utm_params({'utmSource': 'site', 'utmMedium': '', 'utmCampaign': ''})
        self.assertEqual(params, [('utm_source', 'site')])

    def test_add_utm_touches_only_external_links(self):
        html = (
            '<a href="https://other.example/page">внешняя</a>'
            '<a href="/about/">внутренняя</a>'
            '<a href="https://shop.example/own">своя</a>'
            '<a href="https://other.example/x?utm_source=old">с меткой</a>'
        )
        brand = {'utmSource': 'aura', 'utmMedium': '', 'utmCampaign': ''}
        result = add_utm(html, brand, own_prefix='https://shop.example')
        self.assertIn('https://other.example/page?utm_source=aura', result)
        self.assertIn('/about/', result)
        self.assertIn('https://shop.example/own"', result)
        self.assertIn('utm_source=old', result)
        self.assertEqual(result.count('utm_source=aura'), 1)

    def test_add_utm_escapes_cyrillic(self):
        html = '<a href="https://other.example/">x</a>'
        result = add_utm(html, {'utmSource': 'моя'})
        self.assertIn('utm_source=%D0%BC%D0%BE%D1%8F', result)


class BrandApiBase(APITestCase):
    """Общая подготовка: владелец, проект и вход в API."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('brander', 'brand@example.com', 'verysecret123')
        Subscription.objects.create(user=self.user, plan='start')
        self.project = Project.objects.create(
            name='Бренд', tree=default_tree(), owner=self.user, version=1,
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'brander', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')


class BrandApiTests(BrandApiBase):
    def test_brand_is_returned_in_project(self):
        response = self.client.get(f'/api/projects/{self.project.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['brand']['font'], 'sans')

    def test_patch_saves_brand_without_tree(self):
        response = self.client.patch(
            f'/api/projects/{self.project.id}/',
            {'brand': {'accent': '#3366FF', 'signature': 'ООО «Ромашка»'}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.brand['accent'], '#3366FF')
        self.assertEqual(self.project.brand['signature'], 'ООО «Ромашка»')
        # Дерево не затёрто частичным сохранением.
        self.assertEqual(self.project.tree, default_tree())

    def test_bad_accent_is_rejected(self):
        response = self.client.patch(
            f'/api/projects/{self.project.id}/',
            {'brand': {'accent': 'синий'}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class BrandExportTests(BrandApiBase):
    """Брендбук доезжает до пакета, а не только до базы."""

    def build(self):
        version = self.project.versions.create(
            number=2, tree=self.project.tree, author=self.user,
        )
        return build_package(self.project, version, base_url='https://shop.example')

    def test_accent_and_font_reach_stylesheet(self):
        self.project.brand = {'accent': '#3366FF', 'font': 'serif'}
        self.project.save(update_fields=['brand'])
        css = self.build()['files']['assets/css/site.css']
        self.assertIn('--accent: #3366FF', css)
        self.assertIn('Georgia', css)
        self.assertIn('--on-accent: #FFFFFF', css)

    def test_signature_is_rendered_after_main(self):
        self.project.brand = {'signature': 'ООО «Ромашка», ИНН 7700000000'}
        self.project.save(update_fields=['brand'])
        html = self.build()['files']['index.html']
        self.assertIn('class="site-signature"', html)
        self.assertIn('ООО «Ромашка», ИНН 7700000000', html)
        self.assertLess(html.index('</main>'), html.index('site-signature'))

    def test_empty_signature_leaves_no_footer(self):
        html = self.build()['files']['index.html']
        self.assertNotIn('site-signature', html)

    def test_utm_marks_external_button(self):
        tree = default_tree()
        tree['blocks'] = [{
            'id': 'b1', 'module': 'action.link', 'x': 0, 'y': 0,
            'width': 300, 'height': 80, 'label': 'Кнопка',
            'props': {'text': 'В каталог', 'link': 'https://other.example/catalog'},
        }]
        self.project.brand = {'utmSource': 'aura', 'utmMedium': 'social'}
        self.project.save(update_fields=['brand'])
        version = self.project.versions.create(
            number=2, tree=tree, author=self.user,
        )
        html = build_package(self.project, version, base_url='https://shop.example')[
            'files'
        ]['index.html']
        self.assertIn('utm_source=aura', html)
        self.assertIn('utm_medium=social', html)
