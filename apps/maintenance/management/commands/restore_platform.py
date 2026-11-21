"""Восстановление платформы из полного архива.

Останавливайте api и scheduler перед запуском: команда заменяет базу и
каталоги, которые работающие процессы держат открытыми.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from maintenance.platform import (
    check_database_vendor,
    database_file,
    keys_path_after_restore,
    opened_archive,
    restore_database,
    restore_files,
)


class Command(BaseCommand):
    help = (
        'Восстанавливает базу, публикации и медиатеку из архива '
        'backup_platform. Старые каталоги сохраняются рядом.'
    )

    def add_arguments(self, parser):
        parser.add_argument('archive', type=Path, help='путь к tar.gz')
        parser.add_argument(
            '--yes',
            action='store_true',
            help='не спрашивать подтверждение (для автоматизации)',
        )

    def handle(self, *args, **options):
        archive = options['archive']
        if not archive.is_file():
            raise CommandError(f'архив не найден: {archive}')

        with opened_archive(archive) as (staging, manifest):
            self._describe(manifest)
            if not options['yes']:
                self.stdout.write(
                    'ВНИМАНИЕ: база и каталоги будут заменены. '
                    'Старые каталоги сохранятся рядом с пометкой before-restore.'
                )
                try:
                    answer = input('Введите «restore», чтобы продолжить: ')
                except EOFError:
                    raise CommandError(
                        'нет ввода для подтверждения; используйте --yes'
                    ) from None
                if answer.strip() != 'restore':
                    raise CommandError('восстановление отменено')

            # Проверка СУБД — до замены файлов. Иначе архив от другой
            # базы оставил бы новые картинки при старой базе, и откат
            # потребовал бы второго восстановления.
            check_database_vendor(manifest['database']['vendor'])

            restore_files(
                staging,
                manifest,
                log=lambda line: self.stdout.write(line),
            )
            restore_database(
                database_file(staging, manifest),
                manifest['database']['vendor'],
            )
            keys_file = keys_path_after_restore(staging, manifest)

        # Миграции после восстановления: копия могла быть снята более
        # ранней версией платформы, и новый код не должен запускаться на
        # старой схеме.
        call_command('migrate', interactive=False, verbosity=0)

        if keys_file is not None:
            self.stdout.write(
                f'ключи шифрования: {keys_file}. Перенесите значения в '
                'DJANGO_SECRET_ENCRYPTION_KEYS и перезапустите сервисы; '
                'сами по себе они не применились.'
            )
        self.stdout.write(self.style.SUCCESS('восстановление завершено'))

    def _describe(self, manifest: dict) -> None:
        database = manifest.get('database') or {}
        directories = ', '.join(
            f'{entry.get("name")} ({entry.get("files")} файлов)'
            for entry in manifest.get('directories') or []
        ) or 'нет'
        self.stdout.write(
            f'архив: {manifest.get("created_at")}, '
            f'режим {manifest.get("deployment_mode")}, '
            f'база {database.get("vendor")}'
        )
        self.stdout.write(f'каталоги: {directories}')
