"""Резервное копирование и восстановление платформы (ТЗ п.16.4).

Тесты проверяют то, ради чего копия существует: архив содержит базу и
файлы, испорченный архив отвергается до записи, чужую СУБД восстановить
нельзя, а старое содержимое не пропадает при восстановлении.
"""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import TestCase, override_settings

from .platform import (
    FORMAT,
    check_database_vendor,
    create_backup,
    current_directories,
    opened_archive,
    restore_files,
    restore_sqlite,
)


class BackupCase(TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='aurabuilder-test-'))
        self.addCleanup(shutil.rmtree, self.root, True)

        self.publish = self.root / 'published'
        self.assets = self.root / 'assets'
        (self.publish / 'sites' / 'demo').mkdir(parents=True)
        (self.publish / 'sites' / 'demo' / 'index.html').write_text(
            '<h1>Привет</h1>', encoding='utf-8'
        )
        self.assets.mkdir()
        (self.assets / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\nfake')

        self.settings = {
            'PUBLISH_ROOT': self.publish,
            'ASSET_ROOT': self.assets,
            'MEDIA_ROOT': '',
        }
        self.archive = self.root / 'backup.tar.gz'

    def make_backup(self, **options):
        with override_settings(**self.settings):
            return create_backup(self.archive, **options)

    def rebuild(self, destination: Path, mutate) -> Path:
        """Пересобрать архив с изменением распакованного содержимого.

        Так проверяется именно реакция на испорченные данные, а не на
        битый gzip: manifest остаётся прежним, меняется только файл.
        """
        work = Path(tempfile.mkdtemp(dir=self.root))
        with tarfile.open(self.archive) as source:
            source.extractall(work, filter='data')
        mutate(work)
        with tarfile.open(destination, 'w:gz') as target:
            for path in sorted(work.rglob('*')):
                target.add(
                    path,
                    arcname=path.relative_to(work).as_posix(),
                    recursive=False,
                )
        return destination


class BackupContentsTests(BackupCase):
    def test_archive_has_manifest_database_and_both_directories(self):
        manifest = self.make_backup()

        self.assertEqual(manifest['format'], FORMAT)
        self.assertEqual(
            manifest['database']['vendor'], connections['default'].vendor
        )
        names = {
            entry['name']: entry for entry in manifest['directories']
        }
        self.assertEqual(names['published']['files'], 1)
        self.assertEqual(names['assets']['files'], 1)

        with tarfile.open(self.archive) as archive:
            members = set(archive.getnames())

        self.assertIn('manifest.json', members)
        self.assertIn(manifest['database']['file'], members)
        self.assertIn('files/published/sites/demo/index.html', members)
        self.assertIn('files/assets/logo.png', members)

    def test_management_command_writes_the_archive(self):
        stdout = io.StringIO()

        with override_settings(**self.settings):
            call_command('backup_platform', output=self.archive, stdout=stdout)

        self.assertTrue(self.archive.is_file())
        self.assertIn('резервная копия', stdout.getvalue())

    def test_secret_keys_are_optional(self):
        with override_settings(
            DJANGO_SECRET_ENCRYPTION_KEYS='k1:c2VjcmV0',
            **self.settings,
        ):
            manifest = create_backup(self.archive, include_secret_keys=True)
            with tarfile.open(self.archive) as archive:
                self.assertIn('keys.env', archive.getnames())

        self.assertTrue(manifest['keys']['included'])


class RestoreFilesTests(BackupCase):
    def test_files_come_back_content_identical(self):
        self.make_backup()
        shutil.rmtree(self.publish)
        shutil.rmtree(self.assets)

        with override_settings(**self.settings):
            with opened_archive(self.archive) as (staging, manifest):
                saved = restore_files(staging, manifest)

        self.assertEqual(saved, [])
        self.assertEqual(
            (self.publish / 'sites' / 'demo' / 'index.html').read_text(encoding='utf-8'),
            '<h1>Привет</h1>',
        )
        self.assertEqual((self.assets / 'logo.png').read_bytes(), b'\x89PNG\r\n\x1a\nfake')

    def test_previous_content_is_kept_next_to_target(self):
        self.make_backup()
        (self.publish / 'sites' / 'demo' / 'index.html').write_text(
            'правка после копии', encoding='utf-8'
        )

        with override_settings(**self.settings):
            with opened_archive(self.archive) as (staging, manifest):
                saved = restore_files(staging, manifest)

        self.assertEqual(len(saved), 2)
        old_publish = next(path for path in saved if path.name.startswith('published.'))
        old_index = old_publish / 'sites' / 'demo' / 'index.html'
        self.assertEqual(old_index.read_text(encoding='utf-8'), 'правка после копии')
        self.assertEqual(
            (self.publish / 'sites' / 'demo' / 'index.html').read_text(encoding='utf-8'),
            '<h1>Привет</h1>',
        )

    def test_corrupted_file_is_rejected_before_writing(self):
        self.make_backup()

        def damage(work: Path) -> None:
            (work / 'files' / 'assets' / 'logo.png').write_bytes(b'broken')

        corrupt = self.rebuild(self.root / 'corrupt.tar.gz', damage)
        (self.assets / 'logo.png').write_bytes(b'current')

        with override_settings(**self.settings):
            with self.assertRaisesMessage(CommandError, 'контрольная сумма'):
                with opened_archive(corrupt):
                    pass

        self.assertEqual((self.assets / 'logo.png').read_bytes(), b'current')

    def test_foreign_database_vendor_is_refused(self):
        self.make_backup()
        foreign_vendor = (
            'sqlite' if connections['default'].vendor != 'sqlite' else 'postgresql'
        )

        def change_vendor(work: Path) -> None:
            manifest_path = work / 'manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['database']['vendor'] = foreign_vendor
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding='utf-8'
            )

        foreign = self.rebuild(self.root / 'foreign.tar.gz', change_vendor)

        with override_settings(**self.settings):
            with opened_archive(foreign) as (_, manifest):
                with self.assertRaisesMessage(CommandError, 'разными СУБД'):
                    check_database_vendor(manifest['database']['vendor'])

    def test_manifest_is_required(self):
        with tarfile.open(self.archive, 'w:gz') as archive:
            archive.add(
                self.assets / 'logo.png',
                arcname='files/assets/logo.png',
            )

        with self.assertRaisesMessage(CommandError, 'manifest.json'):
            with opened_archive(self.archive):
                pass

    def test_manifest_cannot_point_outside_archive(self):
        self.make_backup()

        def escape(work: Path) -> None:
            manifest_path = work / 'manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['database']['file'] = '../outside.sqlite3'
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding='utf-8'
            )

        escaped = self.rebuild(self.root / 'escaped.tar.gz', escape)

        with self.assertRaisesMessage(CommandError, 'за пределы архива'):
            with opened_archive(escaped):
                pass


class SQLiteRestoreTests(TestCase):
    def test_snapshot_is_restored_into_a_clean_database(self):
        root = Path(tempfile.mkdtemp(prefix='aurabuilder-sqlite-'))
        self.addCleanup(shutil.rmtree, root, True)

        snapshot = root / 'snapshot.sqlite3'
        connection = sqlite3.connect(str(snapshot))
        connection.execute('CREATE TABLE note (text TEXT)')
        connection.execute('INSERT INTO note VALUES (?)', ('сохранено',))
        connection.commit()
        connection.close()

        target = root / 'target.sqlite3'
        restore_sqlite(snapshot, target)

        restored = sqlite3.connect(str(target))
        try:
            row = restored.execute('SELECT text FROM note').fetchone()
        finally:
            restored.close()
        self.assertEqual(row, ('сохранено',))


class DirectoryListTests(TestCase):
    @override_settings(
        PUBLISH_ROOT=Path('published'),
        ASSET_ROOT=Path('assets'),
        MEDIA_ROOT='',
    )
    def test_empty_media_root_is_not_backed_up(self):
        names = [name for name, _ in current_directories()]

        self.assertEqual(names, ['published', 'assets'])
