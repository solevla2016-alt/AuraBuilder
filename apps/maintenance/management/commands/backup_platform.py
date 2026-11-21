"""Полная резервная копия платформы: база, публикации, медиатека.

Запуск на работающем стенде допустим, но восстановление — только на
остановленном сервисе: оно заменяет файлы, которые раздаёт gunicorn.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from maintenance.platform import create_backup


class Command(BaseCommand):
    help = (
        'Собирает tar.gz с базой, опубликованными сайтами и медиатекой. '
        'Ключи шифрования добавляются только с --include-secret-keys.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=Path,
            default=None,
            help='путь к архиву (по умолчанию — в текущем каталоге)',
        )
        parser.add_argument(
            '--include-secret-keys',
            action='store_true',
            help='добавить DJANGO_SECRET_ENCRYPTION_KEYS в архив (секрет!)',
        )

    def handle(self, *args, **options):
        destination = options['output']
        if destination is None:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            destination = Path.cwd() / f'aurabuilder-backup-{stamp}.tar.gz'

        include_keys = options['include_secret_keys']
        if include_keys:
            self.stderr.write(
                'ВНИМАНИЕ: архив будет содержать ключи шифрования секретов. '
                'Храните его как пароль и не передавайте по открытым каналам.'
            )

        manifest = create_backup(
            destination,
            include_secret_keys=include_keys,
            log=lambda line: self.stdout.write(line),
        )

        size = destination.stat().st_size
        self.stdout.write(
            f'резервная копия: {destination} '
            f'({size} байт, режим {manifest["deployment_mode"]})'
        )
        if include_keys:
            self.stdout.write(
                'ключи шифрования внутри архива: для восстановления '
                'перенесите их в DJANGO_SECRET_ENCRYPTION_KEYS до запуска сервиса'
            )
