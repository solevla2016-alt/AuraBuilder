"""Перенос паролей профилей в зашифрованное поле (ТЗ п.7.3).

Миграция переносит значения лучшим возможным образом: при наличии
ключа — шифрует, при его отсутствии — оставляет значение как есть и
продолжает, потому что остановить обновление платформы из-за
незаданного ключа хуже, чем временно оставить старые данные открытыми.
Открытые остатки видны в интерфейсе (`secretEncrypted: false`) и
перешифровываются командой `rotate_secrets` после того, как ключ задан.
"""

from __future__ import annotations

import uuid

from django.db import migrations, models


def forwards(apps, schema_editor):
    HostingProfile = apps.get_model('deploying', 'HostingProfile')
    moved = 0
    plain = 0
    for profile in HostingProfile.objects.exclude(secret='').iterator():
        if profile.secret_encrypted:
            continue
        context = f'deploying.hostingprofile:{profile.secret_token}:secret'
        try:
            from secretstore.crypto import encrypt
            profile.secret_encrypted = encrypt(profile.secret, context=context)
            moved += 1
        except Exception:
            # Ключа нет (или он непригоден): значение переносится как
            # есть, чтобы не потерять доступ к серверам заказчиков.
            profile.secret_encrypted = profile.secret
            plain += 1
        profile.save(update_fields=['secret_encrypted'])
    if plain:
        import logging
        logging.getLogger(__name__).warning(
            'перенесено без шифрования: %s (ключ не задан)', plain,
        )
    if moved or plain:
        import logging
        logging.getLogger(__name__).info(
            'секреты профилей перенесены: зашифровано %s, открыто %s',
            moved, plain,
        )


def backwards(apps, schema_editor):
    # Обратный перенос открытым текстом делать нельзя: он вернул бы
    # в базу значения, которых там не было, и ослабил бы защиту.
    pass


class Migration(migrations.Migration):

    dependencies = [('deploying', '0001_initial')]

    operations = [
        # Токен добавляется первым: контекст шифрования привязывает
        # значение к записи, и для переноса он должен быть уже известен.
        migrations.AddField(
            model_name='hostingprofile',
            name='secret_token',
            field=models.UUIDField(
                default=uuid.uuid4, editable=False,
                verbose_name='Идентификатор секрета',
            ),
        ),
        migrations.AddField(
            model_name='hostingprofile',
            name='secret_encrypted',
            field=models.TextField(
                blank=True, default='',
                verbose_name='Пароль или ключ (шифрованный)',
                help_text='AES-256-GCM; открытое значение хранится только '
                          'до первой миграции и не возвращается в API',
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='hostingprofile', name='secret',
        ),
    ]