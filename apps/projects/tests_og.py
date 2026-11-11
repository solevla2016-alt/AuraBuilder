"""OG-карточки: предпросмотр ссылки в мессенджерах.

Проверяется то, что видит чужой сервер, а не посетитель: PNG нужного
размера, абсолютный адрес карточки при известном домене и отдельная
карточка у внутренней страницы. Повторная сборка обязана дать те же
байты (ТЗ п.16.2), иначе сравнение версий перестало бы работать.
"""

from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from PIL import Image

from projects.models import DocumentVersion, Project, default_tree
from projects.og import HEIGHT, WIDTH, og_card, og_colour
from projects.package import build_package

User = get_user_model()


class OgBase(TestCase):
    """Проект и версия без API: карточка собирается тем же кодом."""

    def setUp(self):
        self.user = User.objects.create_user('oger', 'og@example.com', 'verysecret123')
        self.project = Project.objects.create(
            name='Ромашка', tree=default_tree(), owner=self.user, version=1,
        )

    def version(self, pages=None, number=1):
        return DocumentVersion.objects.create(
            project=self.project,
            number=number,
            tree=self.project.tree,
            pages=pages or [],
            author=self.user,
        )

    def build(self, pages=None, base_url='', number=1):
        return build_package(
            self.project, self.version(pages, number), base_url=base_url,
        )


class OgCardTests(OgBase):
    """Сама картинка: формат, размер и повторяемость."""

    def test_card_is_png_of_og_size(self):
        files = self.build()['files']
        data = files['assets/og/index.png']
        self.assertIsInstance(data, bytes)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        image = Image.open(BytesIO(data))
        self.assertEqual(image.size, (WIDTH, HEIGHT))

    def test_repeat_build_gives_same_bytes(self):
        first = self.build()['files']['assets/og/index.png']
        second = self.build(number=2)['files']['assets/og/index.png']
        self.assertEqual(first, second)

    def test_accent_changes_card(self):
        self.project.brand = {'accent': '#3366FF'}
        self.project.save(update_fields=['brand'])
        blue = self.build()['files']['assets/og/index.png']
        self.project.brand = {'accent': '#FF6633'}
        self.project.save(update_fields=['brand'])
        orange = self.build(number=2)['files']['assets/og/index.png']
        self.assertNotEqual(blue, orange)

    def test_bad_accent_falls_back_to_card_palette(self):
        self.assertEqual(og_colour('синий'), '')
        self.assertEqual(og_colour('#GGGGGG'), '')
        self.assertEqual(og_colour('#3366ff'), '#3366ff')
        # Пустой акцент — не ошибка: карточка рисуется цветом по умолчанию.
        self.assertEqual(
            og_card('Ромашка', 'Главная'),
            og_card('Ромашка', 'Главная', accent=''),
        )


class OgMarkupTests(OgBase):
    """Метатеги в HTML: по ним мессенджер находит карточку."""

    def test_main_page_points_to_its_card(self):
        html = self.build()['files']['index.html']
        self.assertIn('property="og:image" content="assets/og/index.png"', html)
        self.assertIn('name="twitter:card" content="summary_large_image"', html)
        self.assertIn('name="twitter:image" content="assets/og/index.png"', html)

    def test_domain_makes_card_absolute(self):
        result = self.build(base_url='https://shop.example')
        html = result['files']['index.html']
        self.assertIn(
            'property="og:image" content="https://shop.example/assets/og/index.png"',
            html,
        )
        self.assertIn(
            'property="og:url" content="https://shop.example/"', html,
        )

    def test_inner_page_has_own_card_and_relative_path(self):
        pages = [{'slug': 'uslugi', 'title': 'Услуги', 'tree': default_tree()}]
        files = self.build(pages=pages)['files']
        self.assertIn('assets/og/pages/uslugi.png', files)
        self.assertIn('assets/og/index.png', files)
        self.assertNotEqual(
            files['assets/og/index.png'], files['assets/og/pages/uslugi.png'],
        )
        html = files['uslugi/index.html']
        self.assertIn(
            'property="og:image" content="../assets/og/pages/uslugi.png"', html,
        )
        self.assertNotIn('og:url', html)

    def test_inner_page_absolute_path_skips_parent(self):
        pages = [{'slug': 'uslugi', 'title': 'Услуги', 'tree': default_tree()}]
        html = self.build(pages=pages, base_url='https://shop.example/')[
            'files'
        ]['uslugi/index.html']
        self.assertIn(
            'property="og:image" content="https://shop.example/assets/og/pages/uslugi.png"',
            html,
        )
        self.assertIn(
            'property="og:url" content="https://shop.example/uslugi/"', html,
        )

    def test_card_is_listed_in_manifest(self):
        files = self.build()['files']
        manifest = files['build-manifest.json']
        self.assertIn('assets/og/index.png', manifest)
