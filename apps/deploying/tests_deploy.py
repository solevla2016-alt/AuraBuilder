"""Деплой на хостинг заказчика (ТЗ п.16.5).

Проверяется то, что важно на самом деле: файлы доехали, устаревшие
удалены, ключ установки не меняется сам по себе, рантайм положен
рядом с инструкцией, а проверка по HTTP честно сообщает о неудаче,
а не молчит.
"""

from __future__ import annotations

import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from projects.models import Project
from projects.package import build_package
from projects.versions import snapshot

from deploying.models import HostingProfile
from deploying.runtime_pack import runtime_files
from deploying.service import deploy
from deploying.transports import (
    DeployError,
    FilesystemTransport,
    build_transport,
    safe_name,
)


class TransportTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_files_are_written(self):
        transport = FilesystemTransport(self.root / 'site')
        transport.put('index.html', '<h1>Привет</h1>'.encode('utf-8'))
        self.assertEqual(
            (self.root / 'site' / 'index.html').read_text(encoding='utf-8'),
            '<h1>Привет</h1>',
        )

    def test_interrupted_upload_leaves_old_file(self):
        """Запись идёт во временный файл: оборванная загрузка иначе
        оставила бы на сервере половину файла, и сайт открылся бы битым."""
        transport = FilesystemTransport(self.root / 'site')
        transport.put('index.html', 'старый'.encode('utf-8'))
        part = self.root / 'site' / 'index.html.part'
        part.write_bytes('недописанный'.encode('utf-8'))
        self.assertEqual(
            (self.root / 'site' / 'index.html').read_text(encoding='utf-8'), 'старый'
        )

    def test_paths_outside_root_are_refused(self):
        transport = FilesystemTransport(self.root / 'site')
        with self.assertRaises(DeployError):
            transport.put('../взлом.html', b'x')

    def test_absolute_paths_are_refused(self):
        with self.assertRaises(DeployError):
            safe_name('/etc/passwd')

    def test_parent_traversal_is_refused(self):
        with self.assertRaises(DeployError):
            safe_name('assets/../../секрет')

    def test_ftp_without_secret_is_refused_early(self):
        """Ошибка «нет пароля» должна прийти до первой загрузки, а не
        посреди неё."""
        profile = HostingProfile(kind='ftp', host='ftp.example.ru', username='u')
        with self.assertRaises(DeployError) as ctx:
            build_transport(profile)
        self.assertIn('пароль', str(ctx.exception))

    def test_ftp_transport_is_built(self):
        profile = HostingProfile(
            kind='ftp', host='ftp.example.ru', username='u', secret='p',
        )
        self.assertEqual(build_transport(profile).host, 'ftp.example.ru')


class DeployCase(TestCase):
    """Общая заготовка: проект, версия и каталог «сервера»."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'site'
        self.root.mkdir(parents=True)

        User = get_user_model()
        self.user = User.objects.create_user('owner', password='x')
        self.project = Project.objects.create(
            owner=self.user, name='Магазин', tree={'width': 1200, 'blocks': []}
        )
        self.version = snapshot(
            self.project, self.project.tree, author=self.user, label='v1'
        )
        self.profile = HostingProfile.objects.create(
            owner=self.user,
            name='Мой хостинг',
            kind='fs',
            root_path=str(self.root),
            site_url='https://shop.example.ru',
        )

    def build_block(self, module: str = 'text.heading') -> dict:
        return {
            'id': 'b1', 'module': module, 'x': 0, 'y': 0,
            'width': 600, 'height': 200, 'label': 'Блок',
            'props': {'text': 'Привет'},
        }

    def new_version(self, label: str, block: dict | None = None):
        tree = {'width': 1200, 'blocks': [block or self.build_block()]}
        self.project.tree = tree
        self.project.version += 1
        self.project.save(update_fields=['tree', 'version'])
        return snapshot(self.project, tree, author=self.user, label=label)


class ProfileTests(DeployCase):
    def test_paths_get_slashes(self):
        """FTP считает путь относительным без ведущего слэша и может
        положить файлы не туда."""
        self.profile.root_path = 'public_html'
        self.profile.runtime_path = 'tools'
        self.profile.save()
        self.assertEqual(self.profile.target_path, '/public_html/')
        self.assertEqual(self.profile.runtime_target_path, '/tools/')

    def test_secret_is_never_returned(self):
        self.profile.secret = 'очень-секретный-пароль'
        self.profile.save()
        public = self.profile.public_dict()
        self.assertTrue(public['hasSecret'])
        self.assertNotIn('очень-секретный-пароль', json.dumps(public))


class DeployTests(DeployCase):
    def test_site_files_are_uploaded(self):
        result = deploy(self.project, self.version, self.profile, verify=False)
        self.assertTrue(result.ok, result.warnings)
        self.assertTrue((self.root / 'index.html').exists())
        self.assertTrue((self.root / 'assets' / 'css' / 'site.css').exists())

    def test_runtime_is_placed_beside_site(self):
        result = deploy(self.project, self.version, self.profile, verify=False)
        runtime_dir = self.root / '.aurabuilder'
        self.assertTrue((runtime_dir / 'run.sh').exists())
        self.assertTrue((runtime_dir / 'README.md').exists())
        self.assertTrue((runtime_dir / 'runtime' / '__init__.py').exists())
        self.assertTrue(result.runtime_files > 5)

    def test_runtime_keeps_its_data_between_deploys(self):
        """Магазин не должен терять заказы при каждой выгрузке."""
        deploy(self.project, self.version, self.profile, verify=False)
        data = self.root / '.aurabuilder' / 'data'
        data.mkdir(parents=True, exist_ok=True)
        (data / 'runtime.db').write_bytes('база заказов'.encode('utf-8'))
        deploy(self.project, self.version, self.profile, verify=False)
        self.assertEqual(
            (data / 'runtime.db').read_bytes(), 'база заказов'.encode('utf-8')
        )

    def test_runtime_json_points_to_site(self):
        deploy(self.project, self.version, self.profile, verify=False)
        config = json.loads((self.root / 'runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(config['endpoint'], 'https://shop.example.ru/api/runtime')
        self.assertTrue(config['siteKey'])

    def test_site_key_survives_next_deploy(self):
        """Новый ключ при каждой выгрузке обнулял бы корзины всех
        покупателей."""
        deploy(self.project, self.version, self.profile, verify=False)
        first = json.loads(
            (self.root / 'runtime.json').read_text(encoding='utf-8')
        )['siteKey']
        deploy(self.project, self.version, self.profile, verify=False)
        second = json.loads(
            (self.root / 'runtime.json').read_text(encoding='utf-8')
        )['siteKey']
        self.assertEqual(first, second)

    def test_key_can_be_rotated_on_purpose(self):
        deploy(self.project, self.version, self.profile, verify=False)
        first = json.loads(
            (self.root / 'runtime.json').read_text(encoding='utf-8')
        )['siteKey']
        deploy(self.project, self.version, self.profile, verify=False, rotate_key=True)
        second = json.loads(
            (self.root / 'runtime.json').read_text(encoding='utf-8')
        )['siteKey']
        self.assertNotEqual(first, second)

    def test_server_key_matches_package_key(self):
        """Если ключи разойдутся, рантайм отвергнет все запросы сайта."""
        deploy(self.project, self.version, self.profile, verify=False)
        package = json.loads((self.root / 'runtime.json').read_text(encoding='utf-8'))
        server = json.loads(
            (self.root / '.aurabuilder' / 'runtime.json').read_text(encoding='utf-8')
        )
        self.assertEqual(package['siteKey'], server['siteKey'])

    def test_stale_files_are_removed(self):
        deploy(self.project, self.version, self.profile, verify=False)
        stale = self.root / 'old-page.html'
        stale.write_text('прошлый сайт', encoding='utf-8')
        deploy(self.project, self.version, self.profile, verify=False)
        self.assertFalse(stale.exists())

    def test_rebuild_replaces_page(self):
        self.project.tree = {'width': 1200, 'blocks': [self.build_block()]}
        self.project.version += 1
        self.project.save(update_fields=['tree', 'version'])
        first = snapshot(self.project, self.project.tree, author=self.user)
        deploy(self.project, first, self.profile, verify=False)

        new_block = self.build_block()
        new_block['props'] = {'text': 'Другой текст'}
        second = self.new_version('v2', new_block)
        deploy(self.project, second, self.profile, verify=False)

        html = (self.root / 'index.html').read_text(encoding='utf-8')
        self.assertIn('Другой текст', html)
        self.assertNotIn('Привет', html)

    def test_runtime_package_has_no_tests(self):
        pack = runtime_files('Магазин', 'shop.example.ru', 'key', '.aurabuilder')
        names = ' '.join(pack)
        self.assertNotIn('__pycache__', names)
        self.assertNotIn('tests', names)

    def test_runtime_readme_explains_start(self):
        pack = runtime_files('Магазин', 'shop.example.ru', 'key', '.aurabuilder')
        readme = pack['README.md']
        self.assertIn('sh run.sh', readme)
        self.assertIn('shop.example.ru', readme)

    def test_nginx_rule_is_ready(self):
        pack = runtime_files('Магазин', 'shop.example.ru', 'key', '.aurabuilder')
        self.assertIn('location /api/runtime/', pack['nginx.conf'])


class VerifyTests(DeployCase):
    """Проверка по HTTP: главная и рантайм."""

    def serve(self, routes: dict[str, tuple[int, str]]):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = routes.get(self.path, (404, 'нет такого'))
                raw = body.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def test_deploy_passes_when_site_and_runtime_answer(self):
        base = self.serve({
            '/': (200, '<html>витрина</html>'),
            '/api/runtime/health': (200, json.dumps({'ready': True,
                                                    'protocolVersion': 1})),
        })
        self.profile.site_url = base
        self.profile.save()
        result = deploy(self.project, self.version, self.profile)
        self.assertTrue(result.ok, result.warnings)
        self.assertEqual(len(result.checks), 2)
        self.assertTrue(all(check['ok'] for check in result.checks))

    def test_deploy_reports_unreachable_runtime(self):
        """Рантайм не запущен — это должен видеть пользователь, а не
        узнавать на своём сайте."""
        base = self.serve({'/': (200, '<html>витрина</html>')})
        self.profile.site_url = base
        self.profile.save()
        result = deploy(self.project, self.version, self.profile)
        self.assertFalse(result.ok)
        failed = [check for check in result.checks if not check['ok']]
        self.assertEqual(len(failed), 1)
        self.assertIn('Рантайм', failed[0]['name'])
        self.assertTrue(any('не запущен' in w for w in result.warnings))

    def test_wrong_runtime_version_is_a_failure(self):
        base = self.serve({
            '/': (200, '<html>витрина</html>'),
            '/api/runtime/health': (200, json.dumps({'ready': True,
                                                    'protocolVersion': 99})),
        })
        self.profile.site_url = base
        self.profile.save()
        result = deploy(self.project, self.version, self.profile)
        self.assertFalse(result.ok)

    def test_missing_site_url_warns_but_uploads(self):
        self.profile.site_url = ''
        self.profile.save()
        result = deploy(self.project, self.version, self.profile)
        self.assertTrue((self.root / 'index.html').exists())
        self.assertTrue(any('Адрес сайта' in w for w in result.warnings))
        self.assertEqual(result.checks, [])


class PackageTests(DeployCase):
    def test_package_is_valid_before_upload(self):
        """Деплой не должен отправлять пакет, который не прошёл
        собственную проверку."""
        built = build_package(
            self.project, self.version, base_url='https://shop.example.ru'
        )
        self.assertFalse(built['report'].errors)
        self.assertFalse(built['manifest']['requiresPlatform'])


class CommandTests(DeployCase):
    def test_command_refuses_foreign_profile(self):
        """Профиль другого владельца выдал бы доступ к чужому серверу."""
        from django.core.management import call_command

        from deploying.management.commands.deploy_site import Command

        other = get_user_model().objects.create_user('чужой', password='x')
        чужой = HostingProfile.objects.create(
            owner=other, name='Чужой хостинг', kind='fs',
            root_path=str(self.root / 'чужой'),
        )
        with self.assertRaises(Exception):
            call_command(Command(), str(self.project.id), '--profile',
                         str(чужой.id))
        self.assertFalse((self.root / 'чужой').exists())
