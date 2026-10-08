"""Экспорт в статический пакет (ТЗ п.16.4).

Проверяется не «метод вернул строку», а то, ради чего экспорт
существует: архив открывается автономно, внешних ссылок в нём нет, а
одна и та же версия даёт один и тот же результат.
"""

import hashlib
import io
import json
import zipfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from data_sources.models import DataRecord, DataSource
from projects.export import ExportError, esc, slugify
from projects.models import DocumentVersion, Project, default_tree
from projects.package import build_package, package_zip, validate_files

User = get_user_model()


class ExportTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('tester', 'tester@example.com', 'verysecret123')
        self.project = Project.objects.create(
            name='Магазин цветов', tree=default_tree(), owner=self.user, version=1
        )
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'tester', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')

    def snapshot(self, tree=None, number=2) -> DocumentVersion:
        return DocumentVersion.objects.create(
            project=self.project,
            number=number,
            tree=tree or self.project.tree,
            author=self.user,
        )

    def build(self, version, base_url='https://shop.example'):
        return build_package(self.project, version, base_url=base_url)

    def archive(self, files: dict) -> zipfile.ZipFile:
        _, blob = package_zip(files)
        return zipfile.ZipFile(io.BytesIO(blob))


class PackageStructureTests(ExportTestCase):
    def test_package_has_required_files(self):
        # Структура архива задана ТЗ п.16.4: без robots.txt и
        # sitemap.xml сайт не индексируется, без манифеста сборку
        # невозможно повторить и сверить.
        files = self.build(self.snapshot()).get('files') or self.build(self.snapshot())['files']
        for name in (
            'index.html',
            'assets/css/site.css',
            'robots.txt',
            'sitemap.xml',
            'build-manifest.json',
            'README.md',
        ):
            self.assertIn(name, files)

    def test_manifest_records_version_and_checksums(self):
        version = self.snapshot(number=7)
        manifest = self.build(version)['manifest']
        self.assertEqual(manifest['documentVersion'], 7)
        self.assertEqual(manifest['formatVersion'], 1)
        self.assertFalse(manifest['requiresPlatform'])
        self.assertEqual(manifest['externalDependencies'], [])
        # Контрольные суммы считаются по содержимому, а не по имени
        # файла: иначе подмена содержимого осталась бы незамеченной.
        self.assertIn('index.html', manifest['files'])
        expected = hashlib.sha256(
            self.build(version)['files']['index.html'].encode('utf-8')
        ).hexdigest()
        self.assertEqual(manifest['files']['index.html'], expected)

    def test_manifest_lists_modules(self):
        manifest = self.build(self.snapshot())['manifest']
        self.assertIn('section.hero', manifest['modules'])
        self.assertEqual(manifest['blocks'], len(self.project.tree['blocks']))


class AutonomousTests(ExportTestCase):
    def test_no_external_links(self):
        # Главное требование пакета: он должен открыться на чужом
        # хостинге без платформы и без интернета (п.16.4, п.15.3).
        files = self.build(self.snapshot())['files']
        joined = '\n'.join(files.values())
        for host in (
            'fonts.googleapis.com',
            'fonts.gstatic.com',
            'cdnjs',
            'unpkg.com',
            'google-analytics',
        ):
            self.assertNotIn(host, joined, host)

    def test_styles_are_inline_file_without_imports(self):
        css = self.build(self.snapshot())['files']['assets/css/site.css']
        self.assertNotIn('@import', css)
        self.assertNotIn('http://', css)
        self.assertNotIn('https://', css)

    def test_html_is_utf8_with_charset(self):
        # Без charset русский текст в браузере разъезжается, и это
        # первое, что видит заказчик.
        html = self.build(self.snapshot())['files']['index.html']
        self.assertIn('charset="utf-8"', html)
        self.assertIn('lang="ru"', html)

    def test_text_is_escaped(self):
        tree = default_tree()
        tree['blocks'][1]['content'] = '<script>alert(1)</script>'
        version = self.snapshot(tree=tree)
        html = self.build(version)['files']['index.html']
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_archive_contains_only_declared_files(self):
        files = self.build(self.snapshot())['files']
        archive = self.archive(files)
        self.assertEqual(sorted(archive.namelist()), sorted(files))


class DeterminismTests(ExportTestCase):
    def test_same_version_produces_same_content(self):
        # ТЗ п.16.2: повторный экспорт той же версии даёт тот же
        # результат. Время в архиве фиксировано, поэтому и байты
        # совпадают — иначе сравнивать сборки было бы нечем.
        version = self.snapshot(number=5)
        _, first = package_zip(self.build(version)['files'])
        _, second = package_zip(self.build(version)['files'])
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())

    def test_checksums_stable_while_timestamp_changes(self):
        version = self.snapshot(number=5)
        first = self.build(version)['manifest']
        second = self.build(version)['manifest']
        self.assertEqual(first['files'], second['files'])
        # Время сборки может совпасть, но сравнивать его нельзя:
        # оно и не участвует в контрольных суммах.
        self.assertIn('builtAt', second)


class ValidationTests(ExportTestCase):
    def test_external_link_is_error(self):
        files = {'index.html': '<html><head><link href="https://fonts.gstatic.com/x"></head></html>'}
        report = validate_files(files)
        self.assertFalse(report.ok)
        self.assertTrue(any('fonts.gstatic.com' in e for e in report.errors))

    def test_missing_index_is_error(self):
        report = validate_files({'robots.txt': 'User-agent: *'})
        self.assertFalse(report.ok)

    def test_missing_seo_files_are_errors(self):
        files = {'index.html': '<html lang="ru"><head><meta charset="utf-8"><meta property="og:title" content="x"></head><body></body></html>'}
        report = validate_files(files)
        self.assertFalse(report.ok)
        self.assertTrue(any('robots.txt' in e for e in report.errors))

    def test_unclosed_page_is_error(self):
        files = {
            'index.html': '<html lang="ru"><head><meta charset="utf-8"><meta property="og:title" content="x">',
            'robots.txt': '',
            'sitemap.xml': '',
            'build-manifest.json': '{}',
        }
        report = validate_files(files)
        self.assertFalse(report.ok)

    def test_missing_open_graph_is_warning_not_error(self):
        # Отсутствие OG не делает пакет непригодным: сайт работает и
        # индексируется. Блокирующей ошибкой это быть не должно.
        files = {
            'index.html': '<html lang="ru"><head><meta charset="utf-8"></head><body></body></html>',
            'robots.txt': 'User-agent: *',
            'sitemap.xml': '<urlset/>',
            'build-manifest.json': '{}',
        }
        report = validate_files(files)
        self.assertTrue(report.ok)
        self.assertTrue(report.warnings)


class DataExportTests(ExportTestCase):
    def test_records_of_referenced_source_land_in_package(self):
        source = DataSource.objects.create(
            project=self.project,
            name='Товары',
            key='tovary',
            fields=[{'key': 'title', 'label': 'Название', 'type': 'text', 'required': True}],
        )
        DataRecord.objects.create(source=source, data={'title': 'Роза'})
        tree = default_tree()
        tree['blocks'].append(
            {
                'id': 'b5',
                'module': 'data.collection',
                'x': 40,
                'y': 560,
                'width': 640,
                'height': 160,
                'label': 'Каталог',
                'props': {'source': str(source.id)},
            }
        )
        version = self.snapshot(tree=tree)
        files = self.build(version)['files']
        self.assertIn('assets/data/data.json', files)
        payload = json.loads(files['assets/data/data.json'])
        self.assertIn(str(source.id), payload)
        self.assertEqual(payload[str(source.id)], ['Роза'])

    def test_unreferenced_source_is_not_exported(self):
        # Выгружать все источники проекта значило бы положить в
        # архив данные, до которых страница не дотягивается.
        DataSource.objects.create(
            project=self.project,
            name='Скрытый',
            key='hidden',
            fields=[{'key': 'title', 'label': 'Название', 'type': 'text', 'required': True}],
        )
        DataRecord.objects.create(
            source=DataSource.objects.get(key='hidden'), data={'title': 'Секрет'}
        )
        files = self.build(self.snapshot())['files']
        self.assertNotIn('assets/data/data.json', files)

    def test_empty_source_renders_honest_placeholder(self):
        # Пустой источник не заменяется выдуманными строками:
        # заказчик должен видеть, что данных нет.
        source = DataSource.objects.create(
            project=self.project,
            name='Пусто',
            key='empty',
            fields=[{'key': 'title', 'label': 'Название', 'type': 'text', 'required': True}],
        )
        tree = default_tree()
        tree['blocks'].append(
            {
                'id': 'b5',
                'module': 'data.collection',
                'x': 40,
                'y': 560,
                'width': 640,
                'height': 160,
                'label': 'Каталог',
                'props': {'source': str(source.id)},
            }
        )
        html = self.build(self.snapshot(tree=tree))['files']['index.html']
        self.assertIn('Нет записей', html)


class UnsupportedModuleTests(ExportTestCase):
    """Модуль, который не умеет рендериться, отменяет весь экспорт.

    Сейчас таких модулей нет: покрыты все 65. Тест остаётся, потому что
    следующий модуль из реестра может прийти без рендерера, и молча
    пропустить его — значило бы отдать пакет с дырой (п.16.2).
    """

    def test_unknown_module_fails_export(self):
        tree = default_tree()
        tree['blocks'][0]['module'] = 'section.not-a-module'
        with self.assertRaises(ExportError):
            self.build(self.snapshot(tree=tree))

    def test_partial_export_is_impossible(self):
        # Второй блок неизвестен — падает весь экспорт, а не «первая
        # половина страницы».
        tree = default_tree()
        tree['blocks'][1]['module'] = 'section.not-a-module'
        with self.assertRaises(ExportError):
            self.build(self.snapshot(tree=tree))


class ExportEndpointTests(ExportTestCase):
    """Выдача архива через API."""

    def test_export_returns_zip(self):
        self.snapshot()
        response = self.client.get(f'/api/projects/{self.project.id}/export/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/zip')
        disposition = response['Content-Disposition']
        self.assertIn('attachment;', disposition)
        # Имя файла безопасно для HTTP-заголовка: кириллица там
        # кодируется платформой в нечитаемый вид.
        self.assertTrue(disposition.isascii(), disposition)
        self.assertIn('-static.zip', disposition)
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.assertIn('index.html', archive.namelist())

    def test_export_uses_requested_version(self):
        first = self.snapshot(number=2)
        tree = default_tree()
        tree['blocks'][1]['content'] = 'Вторая версия'
        self.snapshot(tree=tree, number=3)
        response = self.client.get(
            f'/api/projects/{self.project.id}/export/?version={first.number}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        html = zipfile.ZipFile(io.BytesIO(response.content)).read('index.html').decode('utf-8')
        # Содержимое именно запрошенной версии, а не последней.
        self.assertNotIn('Вторая версия', html)

    def test_export_without_versions_conflicts(self):
        # Проект, который ещё ни разу не менялся, выгружать нечего:
        # пакет собрался бы из состояния, которого нет в истории.
        response = self.client.get(f'/api/projects/{self.project.id}/export/')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_unknown_version_404(self):
        self.snapshot()
        response = self.client.get(f'/api/projects/{self.project.id}/export/?version=99')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_bad_version_400(self):
        self.snapshot()
        response = self.client.get(f'/api/projects/{self.project.id}/export/?version=abc')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_viewer_cannot_export(self):
        # Выгрузка ограничена тарифами отдельно от просмотра (п.17.1),
        # поэтому роль решает: Viewer видит черновик, но не забирает его.
        from accounts.models import Membership, Role

        viewer = User.objects.create_user('viewer', 'v@example.com', 'verysecret123')
        Membership.objects.create(project=self.project, user=viewer, role=Role.VIEWER)
        self.snapshot()
        response = self.client.post(
            '/api/auth/login/',
            {'login': 'viewer', 'password': 'verysecret123'},
            format='json',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + response.data['access']
        )
        forbidden = self.client.get(f'/api/projects/{self.project.id}/export/')
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

    def test_export_logs_audit_entry(self):
        # Журнал действий (ТЗ п.11.2): выгрузка проекта — событие, по
        # которому можно доказать, что данные покидали платформу.
        from accounts.models import AuditLog

        self.snapshot()
        self.client.get(f'/api/projects/{self.project.id}/export/')
        self.assertTrue(
            AuditLog.objects.filter(project=self.project, action='project.export').exists()
        )


class RenderedTextTests(ExportTestCase):
    """Текст блока доезжает до пакета так же, как его видно в редакторе.

    Проверяется ровно то, что не сходилось: панель свойств называет
    поле «Название» и пишет его в label, а экспорт смотрел только в
    props. Правка названия блока молча не попадала в выгрузку.
    """

    def test_label_is_used_when_no_content(self):
        tree = default_tree()
        tree['blocks'][1]['label'] = 'Проверка выгрузки'
        html = self.build(self.snapshot(tree=tree))['files']['index.html']
        self.assertIn('Проверка выгрузки', html)

    def test_content_wins_over_label(self):
        # Содержимое — то, что человек печатает в поле содержимого;
        # оно важнее технической подписи блока.
        tree = default_tree()
        tree['blocks'][1]['label'] = 'Подпись блока'
        tree['blocks'][1]['content'] = 'Живой текст'
        html = self.build(self.snapshot(tree=tree))['files']['index.html']
        self.assertIn('Живой текст', html)
        self.assertNotIn('Подпись блока', html)

    def test_props_win_over_everything(self):
        tree = default_tree()
        tree['blocks'][1]['label'] = 'Подпись'
        tree['blocks'][1]['content'] = 'Содержимое'
        tree['blocks'][1]['props'] = {'text': 'Свойство'}
        html = self.build(self.snapshot(tree=tree))['files']['index.html']
        self.assertIn('Свойство', html)

    def test_section_heading_from_label(self):
        tree = default_tree()
        tree['blocks'][0]['label'] = 'Первый экран магазина'
        html = self.build(self.snapshot(tree=tree))['files']['index.html']
        self.assertIn('Первый экран магазина', html)


class HelperTests(APITestCase):
    """Мелочи, на которых держится остальное."""

    def test_slugify_handles_cyrillic(self):
        self.assertEqual(slugify('Розы и букеты'), 'розы-и-букеты')
        self.assertEqual(slugify('Product #1'), 'product-1')
        self.assertEqual(slugify('   '), 'page')

    def test_escape_covers_quotes(self):
        # Без экранирования кавычек атрибут можно разорвать и вставить
        # своё событие — это XSS на сайте заказчика.
        self.assertEqual(esc('a" onload="x'), 'a&quot; onload=&quot;x')
        self.assertEqual(esc("it's"), 'it&#39;s')
        self.assertEqual(esc(None), '')