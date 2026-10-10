"""Создание владельца локального стенда.

Зачем: база локального стенда живёт в томе Docker, и вместе с томом
пропадает единственная учётная запись. Восстанавливать её вручную
через `shell` каждый раз — это шаг, который рано или поздно забывают,
и стенд выглядит исправным до первого входа: страница открывается,
а войти нельзя.

Команда идемпотентна: существующего пользователя она не ломает, а
сообщает, что он уже есть. Пароль берётся из аргумента или из
переменной окружения, но не из аргумента по умолчанию — значение по
умолчанию осталось бы в истории командной строки.

Запуск:

    python manage.py create_owner --username owner
    python manage.py create_owner --username owner --password 'пароль'
    STEND_OWNER_PASSWORD='пароль' python manage.py create_owner
"""

from __future__ import annotations

import os
import sys

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction


class Command(BaseCommand):
    help = 'Создаёт пользователя локального стенда (или обновляет его пароль).'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True, help='Имя пользователя для входа.')
        parser.add_argument('--email', default='', help='Почта. Необязательна для стенда.')
        parser.add_argument(
            '--password',
            default='',
            help='Пароль. Если не задан, берётся из STEND_OWNER_PASSWORD.',
        )
        parser.add_argument(
            '--reset-password',
            action='store_true',
            help='Обновить пароль, если пользователь уже существует.',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username'].strip()
        password = options['password'] or os.environ.get('STEND_OWNER_PASSWORD', '')

        if not username:
            raise CommandError('имя пользователя не может быть пустым')

        # Пароль короче восьми символов Django не примет: это не наше
        # ограничение, и сообщение об ошибке сбивало бы с толку.
        if password and len(password) < 8:
            raise CommandError('пароль короче 8 символов — Django его не примет')

        with transaction.atomic():
            user = User.objects.filter(username=username).first()
            created = user is None

            if created:
                user = User.objects.create_user(
                    username=username,
                    email=options['email'] or '',
                    password=password or None,
                )
                self.stdout.write(self.style.SUCCESS(f'создан пользователь {username}'))
            else:
                self.stdout.write(f'пользователь {username} уже существует')

            # Пароль без --reset-password не трогаем: иначе повторный
            # запуск команды с пустым STEND_OWNER_PASSWORD стёр бы
            # пароль, который человек уже задал.
            if password and (created or options['reset_password']):
                user.set_password(password)
                user.save(update_fields=['password'])
                self.stdout.write(self.style.SUCCESS('пароль установлен'))
            elif not created:
                self.stdout.write('пароль не изменён (нужен --reset-password)')

            if not user.is_active:
                user.is_active = True
                user.save(update_fields=['is_active'])
                self.stdout.write(self.style.WARNING('учётная запись была неактивна — включена'))

        if created and not password:
            self.stdout.write(self.style.WARNING(
                'пароль не задан: войти будет нельзя. Задайте STEND_OWNER_PASSWORD '
                'и запустите команду с --reset-password.',
            ))
            sys.exit(1)

        self.stdout.write('готово: вход выполняется на логине ' + username)