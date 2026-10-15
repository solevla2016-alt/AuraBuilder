"""Генерация ключа шифрования секретов.

Ключ выводится, а не записывается в настройки: значение должно попасть
в менеджер секретов платформы, а не в репозиторий. Команда ничего не
меняет в базе — она только помогает не ошибиться при копировании.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from secretstore.crypto import generate_key, keyring


class Command(BaseCommand):
    help = ('Показывает ключ шифрования секретов и проверяет кольцо. '
            'Новый ключ: --generate <идентификатор>')

    def add_arguments(self, parser):
        parser.add_argument(
            '--generate', metavar='KID', default='',
            help='сгенерировать новый ключ с идентификатором KID '
                 '(например, 2027-01)',
        )

    def handle(self, *args, **options):
        kid = options['generate']
        if kid:
            self.stdout.write(generate_key(kid))
            self.stdout.write(
                'Добавьте значение в DJANGO_SECRET_ENCRYPTION_KEYS первым — '
                'тогда новые секреты будут шифроваться им, а старые '
                'останутся читаемыми, пока не перешифрованы командой '
                'rotate_secrets.',
            )
            return

        keys = keyring()
        if not keys:
            self.stderr.write(
                'Кольцо ключей пусто: секреты не хранятся. '
                'Сгенерируйте ключ: manage.py secret_key --generate 2026-10',
            )
            raise SystemExit(1)
        self.stdout.write(f'ключей в кольце: {len(keys)}')
        for index, key in enumerate(keys):
            role = 'активный (шифрование)' if index == 0 else 'только чтение'
            self.stdout.write(f'  {key.kid}: {role}')