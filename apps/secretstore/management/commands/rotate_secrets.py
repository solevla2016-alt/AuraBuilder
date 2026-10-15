"""Перешифровка секретов активным ключом — шаг ротации.

Порядок ротации (ADR-0007):

1. новый ключ добавляется первым в DJANGO_SECRET_ENCRYPTION_KEYS;
2. выполняется `manage.py rotate_secrets` — значения перешифровываются
   новым ключом, старый остаётся в кольце для чтения;
3. старый ключ удаляется из кольца.

Шаг между 2 и 3 обязателен: удалить ключ раньше — значит потерять
секреты, которые ещё не перешифрованы.
"""

from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from secretstore.crypto import SecretsUnavailable, SecretUnreadable
from secretstore.services import SecretMixin


class Command(BaseCommand):
    help = ('Перешифровывает секреты активным ключом. '
            'Повторный запуск безопасен.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='показать, что изменится, ничего не писать')

    def handle(self, *args, **options):
        dry = options['dry_run']
        total = changed = failed = 0
        for model in apps.get_models():
            if not issubclass(model, SecretMixin):
                continue
            if not hasattr(model, 'secret_encrypted'):
                continue
            for obj in model.objects.filter(secret_encrypted__gt='').iterator():
                total += 1
                try:
                    if obj.rotate_secret():
                        changed += 1
                        if not dry:
                            obj.save(update_fields=['secret_encrypted'])
                except (SecretUnreadable, SecretsUnavailable) as e:
                    failed += 1
                    self.stderr.write(f'{obj}: {e}')

        verb = 'будет перешифровано' if dry else 'перешифровано'
        self.stdout.write(
            f'секретов: {total}, {verb}: {changed}, не прочитано: {failed}',
        )
        if failed:
            # Не молчаливый выход: после удаления старого ключа такие
            # значения стали бы недоступны навсегда.
            raise CommandError(
                'часть секретов не расшифровалась; ключ из их префикса '
                'верните в кольцо и повторите',
            )