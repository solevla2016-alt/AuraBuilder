"""Медиатека проекта: приём, отказ и попадание в пакет (ТЗ п.4.3).

Проверяется не «файл сохранился», а три вещи, на которых держится
доверие: чужой формат не проходит, исполняемый SVG не проходит, а
собранный пакет работает без платформы.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Membership
from accounts.permissions import Role

from projects.models import Project, default_tree
from projects.package import build_package, package_zip
from projects.versions import snapshot

from .models import Asset
from .services import save_upload
from .storage import AssetRejected, project_dir, remove, store, url_for

User = get_user_model()

#: Каталог файлов на каждый класс: тесты пишут настоящие файлы, и без
#: своего каталога они оставались бы в общем хранилище стенда. Общий
#: каталог ещё и означал бы, что тест видит чужие файлы и падает не из-
#: за своего кода.
def _asset_root() -> Path:
    return Path(tempfile.mkdtemp(prefix='ab-assets-'))

PNG = (b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + b'\x00' * 40)
GIF = b'GIF89a' + b'\x00' * 40
SAFE_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            b'<rect width="10" height="10" fill="#fff"/></svg>')
EVIL_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script>'
            b'</svg>')


def upload(name: str, content: bytes, content_type: str = 'image/png'):
    return SimpleUploadedFile(name, content, content_type=content_type)


class AssetRootMixin:
    """Свой каталог файлов на каждый класс тестов."""

    @classmethod
    def setUpClass(cls):
        cls.assets_dir = _asset_root()
        cls.assets_override = override_settings(ASSET_ROOT=cls.assets_dir)
        cls.assets_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.assets_override.disable()
        shutil.rmtree(cls.assets_dir, ignore_errors=True)


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class UploadApiTests(AssetRootMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        self.editor = User.objects.create_user('editor', password='pass-ed')
        self.project = Project.objects.create(owner=self.owner, name='Магазин')
        # Редактор должен быть участником проекта: пользователь без
        # роли получает 404, и этим проверяется уже другое правило.
        Membership.objects.create(project=self.project, user=self.editor,
                                  role=Role.EDITOR)
        self.client = APIClient()
        self.login()

    def login(self, username='owner', password='pass-owner'):
        response = self.client.post('/api/auth/login/',
                                    {'login': username, 'password': password},
                                    format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + response.data['access'])

    def send(self, file):
        return self.client.post(
            f'/api/projects/{self.project.id}/assets/',
            {'file': file}, format='multipart',
        )

    def test_png_is_accepted(self):
        response = self.send(upload('меню.png', PNG))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['contentType'], 'image/png')
        self.assertTrue(response.data['url'].endswith('/file/'))

    def test_gif_is_accepted(self):
        response = self.send(upload('.gif', GIF, 'image/gif'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['contentType'], 'image/gif')

    def test_svg_is_accepted_when_safe(self):
        response = self.send(upload('лого.svg', SAFE_SVG, 'image/svg+xml'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['contentType'], 'image/svg+xml')

    def test_svg_with_script_is_refused(self):
        # SVG исполняет код от имени страницы: пропустить такой файл
        # значит отдать посетителю чужой скрипт от имени клиента.
        response = self.send(upload('logo.svg', EVIL_SVG, 'image/svg+xml'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('исполняемый код', response.data['detail'])

    def test_renamed_executable_is_refused(self):
        response = self.send(upload('photo.png', b'MZ\x90\x00' + b'\x00' * 40))
        self.assertEqual(response.status_code, 400)
        self.assertIn('только изображения', response.data['detail'])

    def test_empty_file_is_refused(self):
        response = self.send(upload('пусто.png', b''))
        self.assertEqual(response.status_code, 400)

    def test_oversized_file_is_refused(self):
        with override_settings(LIMITS={**self.settings_dict(),
                                       'MAX_UPLOAD_BYTES': 10}):
            response = self.send(upload('big.png', PNG + b'\x00' * 100))
        self.assertEqual(response.status_code, 400)
        self.assertIn('МБ', response.data['detail'])

    def settings_dict(self) -> dict:
        from django.conf import settings

        return settings.LIMITS

    def test_editor_cannot_upload(self):
        self.login('editor', 'pass-ed')
        response = self.send(upload('меню.png', PNG))
        self.assertEqual(response.status_code, 403)

    def test_outsider_sees_nothing(self):
        outsider = User.objects.create_user('outsider', password='pass-x')
        self.login('outsider', 'pass-x')
        response = self.client.get(f'/api/projects/{self.project.id}/assets/')
        self.assertEqual(response.status_code, 404)

    def test_list_and_delete(self):
        created = self.send(upload('меню.png', PNG)).data
        listing = self.client.get(f'/api/projects/{self.project.id}/assets/')
        self.assertEqual(len(listing.data['assets']), 1)
        removed = self.client.delete(
            f'/api/projects/{self.project.id}/assets/{created["id"]}/')
        self.assertEqual(removed.status_code, 204)
        self.assertFalse(
            Asset.objects.filter(id=created['id']).exists())

    def test_file_is_served(self):
        created = self.send(upload('меню.png', PNG)).data
        response = self.client.get(created['url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), PNG)


class StorageTests(AssetRootMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pass-owner')
        self.project = Project.objects.create(owner=self.owner, name='Магазин')

    def test_stored_file_is_not_the_upload_name(self):
        stored = store(self.project, upload('Моё фото.png', PNG))
        # Имя не должно содержать ни пробелов, ни кириллицы: оно
        # попадает в путь и в URL сборки.
        self.assertTrue(stored.name.endswith('.png'))
        self.assertNotIn(' ', stored.name)
        self.assertNotIn('Моё', stored.name)

    def test_two_same_names_do_not_collide(self):
        first = store(self.project, upload('меню.png', PNG))
        second = store(self.project, upload('меню.png', PNG))
        self.assertNotEqual(first.name, second.name)

    def test_no_partial_files_left(self):
        store(self.project, upload('меню.png', PNG))
        directory = project_dir(self.project)
        self.assertFalse(list(directory.glob('*.part')))


class PackagingTests(AssetRootMixin, TestCase):
    """Медиатека в собранном пакете.

    Проверяется главное свойство экспорта: унесённый архив работает
    без платформы. Если картинка осталась адресом платформы, сайт у
    заказчика покажет пустые места, и это обнаружится позже всех.
    """

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', password='pass-owner')
        self.project = Project.objects.create(owner=self.owner, name='Магазин')

    def add_asset(self, name: str = 'меню.png', content: bytes = PNG) -> Asset:
        """Кладёт файл так же, как это делает API: запись и файл."""
        return save_upload(self.project, upload(name, content))

    def build(self, image_url: str, label: str = 'v1'):
        tree = dict(default_tree())
        tree['blocks'] = [{
            'id': 'b1', 'module': 'media.image', 'x': 0, 'y': 0,
            'width': 600, 'height': 400, 'label': 'Картинка',
            'props': {'src': image_url},
        }]
        version = snapshot(self.project, tree, author=self.owner, label=label)
        return build_package(self.project, version)

    def test_asset_is_in_package(self):
        asset = self.add_asset()
        built = self.build(url_for(self.project, asset.name))
        self.assertTrue(any(n.startswith('assets/img/') for n in built['files']))

    def test_package_zip_contains_image_bytes(self):
        # Картинка должна попасть в архив байт в байт, а не текстом:
        # закодированная в base64 картинка не откроется в браузере.
        asset = self.add_asset()
        built = self.build(url_for(self.project, asset.name))
        _, blob = package_zip(built['files'])
        with zipfile.ZipFile(BytesIO(blob)) as archive:
            packed = archive.read(f'assets/img/{asset.name}')
        self.assertEqual(packed, PNG)

    def test_link_becomes_local(self):
        asset = self.add_asset()
        built = self.build(url_for(self.project, asset.name))
        html = built['files']['index.html']
        self.assertNotIn('/api/projects/', html)
        self.assertIn(f'assets/img/{asset.name}', html)
        # Картинка должна быть настоящим тегом, а не заглушкой:
        # иначе экспорт «соберётся», а на сайте будет пустое место.
        self.assertIn('<img', html)

    def test_package_has_no_external_image_links(self):
        asset = self.add_asset()
        built = self.build(url_for(self.project, asset.name))
        self.assertEqual(built['manifest']['externalDependencies'], [])

    def test_manifest_checksums_match_files(self):
        # Суммы в манифесте обязаны совпадать с файлами в архиве,
        # иначе сравнить две сборки невозможно, а расхождение никто
        # не заметит.
        asset = self.add_asset()
        built = self.build(url_for(self.project, asset.name))
        for name, digest in built['manifest']['files'].items():
            content = built['files'][name]
            raw = content if isinstance(content, bytes) else content.encode('utf-8')
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest, name)

    def test_manifest_reports_media(self):
        asset = self.add_asset()
        built = self.build(url_for(self.project, asset.name))
        self.assertEqual(built['manifest']['assets']['count'], 1)
        self.assertEqual(built['manifest']['assets']['missing'], [])

    def test_gallery_images_become_local(self):
        # Галерея принимает список адресов: переписываются все кадры,
        # а не только первый.
        first = self.add_asset('one.png')
        second = self.add_asset('two.png')
        urls = ','.join([url_for(self.project, first.name),
                         url_for(self.project, second.name)])
        tree = dict(default_tree())
        tree['blocks'] = [{
            'id': 'b1', 'module': 'section.gallery', 'x': 0, 'y': 0,
            'width': 600, 'height': 400, 'label': 'Галерея',
            'props': {'images': urls, 'columns': 2},
        }]
        version = snapshot(self.project, tree, author=self.owner, label='v1')
        built = build_package(self.project, version)
        html = built['files']['index.html']
        self.assertNotIn('/api/projects/', html)
        self.assertIn(f'assets/img/{first.name}', html)
        self.assertIn(f'assets/img/{second.name}', html)
        self.assertEqual(built['manifest']['assets']['count'], 2)

    def test_removed_asset_is_reported_as_missing(self):
        # Ссылка ведёт на файл, которого уже нет: на сайте будет пустое
        # место, и об этом должна говорить сборка, а не посетитель.
        asset = self.add_asset()
        url = url_for(self.project, asset.name)
        asset.delete()
        remove(self.project, asset.name)
        built = self.build(url, label='v2')
        self.assertEqual(built['manifest']['assets']['missing'], [url])
        self.assertIn(url, built['manifest']['externalDependencies'])
        self.assertTrue(
            any('удалённый файл' in w for w in built['manifest']['warnings']),
            built['manifest']['warnings'],
        )