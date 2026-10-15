"""Шифрование секретов (ТЗ п.7.3, ADR-0007).

Проверяется не «зашифровалось ли», а три свойства, на которых держится
защита: значение в базе не читается без ключа, подмена и копирование
между записями обнаруживаются, а ротация не ломает старые секреты.
"""

from __future__ import annotations

import base64

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings

from deploying.models import HostingProfile
from secretstore.crypto import (
    SecretsUnavailable,
    SecretUnreadable,
    decrypt,
    encrypt,
    generate_key,
    is_encrypted,
    keyring,
    reencrypt,
)

User = get_user_model()

#: Ключи для тестов заданы явно: тест не должен зависеть от окружения,
#: в котором его запустили.
KEY_A = generate_key('a')
KEY_B = generate_key('b')


def with_keys(*keys: str):
    return override_settings(
        DJANGO_SECRET_ENCRYPTION_KEYS=','.join(keys),
    )


class KeyRingTests(TestCase):
    def test_empty_ring_is_a_state_not_a_crash(self):
        with with_keys(''):
            self.assertEqual(keyring(), [])

    def test_first_key_is_active(self):
        with with_keys(KEY_A, KEY_B):
            keys = keyring()
            self.assertEqual([k.kid for k in keys], ['a', 'b'])

    def test_duplicate_ids_are_refused(self):
        # Иначе при ротации было бы неясно, какой из двух ключей активен.
        with with_keys(KEY_A, KEY_A):
            with self.assertRaises(SecretsUnavailable):
                keyring()

    def test_short_key_is_refused(self):
        weak = 'weak:' + base64.urlsafe_b64encode(b'short').decode('ascii')
        with with_keys(weak):
            with self.assertRaises(SecretsUnavailable):
                keyring()

    def test_malformed_item_is_skipped(self):
        with with_keys(KEY_A + ',мусор'):
            self.assertEqual([k.kid for k in keyring()], ['a'])


class EncryptDecryptTests(TestCase):
    def test_round_trip(self):
        with with_keys(KEY_A):
            blob = encrypt('пароль-123', context='test:1')
            self.assertEqual(decrypt(blob, context='test:1'), 'пароль-123')

    def test_value_in_database_is_not_the_password(self):
        with with_keys(KEY_A):
            blob = encrypt('пароль-123', context='test:1')
            self.assertNotIn('пароль-123', blob)

    def test_format_carries_key_id(self):
        with with_keys(KEY_A):
            blob = encrypt('x', context='test:1')
            self.assertTrue(blob.startswith('a1.a.'))
            self.assertTrue(is_encrypted(blob))

    def test_nonce_differs_between_calls(self):
        with with_keys(KEY_A):
            first = encrypt('x', context='test:1')
            second = encrypt('x', context='test:1')
            self.assertNotEqual(first, second)

    def test_empty_value_stays_empty(self):
        with with_keys(KEY_A):
            self.assertEqual(encrypt('', context='test:1'), '')
            self.assertEqual(decrypt('', context='test:1'), '')

    def test_ciphertext_from_another_context_is_refused(self):
        # Копирование шифротекста одного профиля в другой не проходит:
        # контекст входит в аутентифицируемые данные.
        with with_keys(KEY_A):
            blob = encrypt('пароль', context='hostingprofile:token-a:secret')
            with self.assertRaises(SecretUnreadable):
                decrypt(blob, context='hostingprofile:token-b:secret')

    def test_tampered_ciphertext_is_refused(self):
        with with_keys(KEY_A):
            blob = encrypt('пароль', context='test:1')
            parts = blob.split('.')
            raw = bytearray(base64.urlsafe_b64decode(parts[3]))
            raw[0] ^= 0xFF
            parts[3] = base64.urlsafe_b64encode(bytes(raw)).decode('ascii')
            with self.assertRaises(SecretUnreadable):
                decrypt('.'.join(parts), context='test:1')

    def test_missing_key_is_a_clear_error(self):
        with with_keys(KEY_A):
            blob = encrypt('пароль', context='test:1')
        with with_keys(KEY_B):
            with self.assertRaises(SecretUnreadable) as ctx:
                decrypt(blob, context='test:1')
            self.assertIn('a', str(ctx.exception))

    def test_without_keys_encryption_is_refused(self):
        with with_keys(''):
            with self.assertRaises(SecretsUnavailable):
                encrypt('пароль', context='test:1')


class RotationTests(TestCase):
    def test_old_key_still_reads_after_rotation(self):
        with with_keys(KEY_A):
            blob = encrypt('пароль', context='test:1')
        # Новый ключ добавлен первым, старый остался в кольце.
        with with_keys(KEY_B, KEY_A):
            self.assertEqual(decrypt(blob, context='test:1'), 'пароль')
            moved = reencrypt(blob, context='test:1')
            self.assertEqual(decrypt(moved, context='test:1'), 'пароль')
            self.assertTrue(moved.startswith('a1.b.'))

    def test_reencrypt_is_idempotent(self):
        with with_keys(KEY_A):
            blob = encrypt('пароль', context='test:1')
            self.assertEqual(reencrypt(blob, context='test:1'), blob)

    def test_rotation_after_new_key_is_needed(self):
        with with_keys(KEY_A):
            blob = encrypt('пароль', context='test:1')
            moved = reencrypt(blob, context='test:1')
        with with_keys(KEY_B):
            with self.assertRaises(SecretUnreadable):
                decrypt(moved, context='test:1')


class LegacyValueTests(TestCase):
    def test_unencrypted_value_is_returned_with_a_warning(self):
        # Значение, перенесённое миграцией без ключа, не должно
        # исчезнуть: им ещё пользуется деплой.
        with self.assertLogs('secretstore.crypto', level='WARNING'):
            self.assertEqual(decrypt('открытый-пароль', context='test:1'),
                             'открытый-пароль')


class HostingProfileSecretTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pass-owner')
        self.patcher_key = with_keys(KEY_A)
        self.patcher_key.enable()

    def tearDown(self):
        self.patcher_key.disable()

    def make(self, secret: str = 'пароль-123') -> HostingProfile:
        profile = HostingProfile(
            owner=self.owner, name='Сайт', kind='ftp', host='ftp.example.ru',
            username='user',
        )
        profile.set_secret(secret)
        profile.save()
        return profile

    def test_secret_is_not_in_the_row(self):
        profile = self.make()
        stored = HostingProfile.objects.get(pk=profile.pk).secret_encrypted
        self.assertNotIn('пароль-123', stored)
        self.assertTrue(stored.startswith('a1.'))

    def test_secret_is_read_back(self):
        profile = self.make()
        reloaded = HostingProfile.objects.get(pk=profile.pk)
        self.assertEqual(reloaded.get_secret(), 'пароль-123')

    def test_public_dict_never_contains_secret(self):
        profile = self.make()
        self.assertNotIn('пароль-123', repr(profile.public_dict()))
        self.assertTrue(profile.public_dict()['hasSecret'])
        self.assertTrue(profile.public_dict()['secretEncrypted'])

    def test_unicode_secret_survives(self):
        profile = self.make('пароль-«ёлка»-🔑')
        self.assertEqual(HostingProfile.objects.get(pk=profile.pk).get_secret(),
                         'пароль-«ёлка»-🔑')

    def test_secret_of_another_profile_cannot_be_read(self):
        first = self.make('первый')
        second = HostingProfile.objects.get(pk=self.make('второй').pk)
        # Шифротекст первого, подставленный во второй, не расшифруется:
        second.secret_encrypted = first.secret_encrypted
        with self.assertRaises(SecretUnreadable):
            second.get_secret()

    def test_rotate_marks_change(self):
        profile = self.make()
        with with_keys(KEY_B, KEY_A):
            self.assertTrue(HostingProfile.objects.get(pk=profile.pk)
                            .rotate_secret())
        self.assertFalse(HostingProfile.objects.get(pk=profile.pk)
                         .rotate_secret())

    def test_empty_secret_is_stored_empty(self):
        profile = HostingProfile(owner=self.owner, name='Без доступа',
                                 kind='fs', root_path='/tmp/site')
        profile.set_secret('')
        profile.save()
        self.assertEqual(profile.secret_encrypted, '')
        self.assertFalse(profile.has_secret)


class MigrationTests(TransactionTestCase):
    """Перенос открытых паролей проверяется на реальных миграциях.

    Именно TransactionTestCase: обычный TestCase держит тест внутри
    транзакции, а переключение миграций меняет схему — под откатом
    транзакции изменения схемы отменяются, и тест проверял бы старую
    таблицу, считая, что перенос состоялся.

    База создана на последней миграции, поэтому её сначала откатывают
    на 0001: без отката историческая модель писала бы в столбец,
    которого в базе уже нет.
    """

    def migrate_to(self, target):
        """Переключает миграции, пересоздавая исполнитель.

        У одного объекта MigrationExecutor кэш применённых миграций не
        обновляется после migrate: второй вызов видел бы прежнее
        состояние, решил бы, что цель уже достигнута, и не сделал бы
        ничего — тест проверял бы старую таблицу, считая, что перенос
        состоялся.
        """
        from django.db.migrations.executor import MigrationExecutor

        MigrationExecutor(self.connection).migrate(target)
        return MigrationExecutor(self.connection)

    def setUp(self):
        from django.db import connection

        self.connection = connection
        executor = self.migrate_to([('deploying', '0001_initial')])
        self.old_apps = executor.loader.project_state(
            [('deploying', '0001_initial')],
        ).apps

    def tearDown(self):
        # База возвращается в состояние, в котором её ожидают остальные
        # тесты этого запуска.
        self.migrate_to([('deploying', '0002_encrypt_hosting_secrets')])

    def legacy_profile(self, username: str, name: str, secret: str):
        Old = self.old_apps.get_model('deploying', 'HostingProfile')
        # Пользователь берётся из того же состояния миграций: у
        # исторических моделей своя копия класса, и пользователь из
        # рабочей модели такой ссылкой быть не может.
        OldUser = self.old_apps.get_model('auth', 'User')
        user = OldUser.objects.create(username=username)
        return Old.objects.create(
            owner=user, name=name, kind='ftp', host='ftp.example.ru',
            username='user', secret=secret,
        )

    def test_open_password_is_migrated_and_field_dropped(self):
        """Старое открытое поле переезжает в зашифрованное и исчезает."""
        with with_keys(KEY_A):
            self.legacy_profile('legacy', 'Старый', 'старый-пароль')
            executor = self.migrate_to(
                [('deploying', '0002_encrypt_hosting_secrets')],
            )
            new_apps = executor.loader.project_state(
                [('deploying', '0002_encrypt_hosting_secrets')],
            ).apps
            New = new_apps.get_model('deploying', 'HostingProfile')
            row = New.objects.get(name='Старый')
            self.assertNotIn('старый-пароль', row.secret_encrypted)
            self.assertTrue(row.secret_encrypted.startswith('a1.'))
            fields = [f.name for f in New._meta.get_fields()
                      if getattr(f, 'concrete', False)]
            self.assertNotIn('secret', fields)
            self.assertIn('secret_encrypted', fields)

    def test_migration_without_keys_keeps_value_readable(self):
        """Без ключа миграция не теряет доступ и не падает."""
        self.legacy_profile('legacy2', 'Без ключа', 'пароль-без-ключа')
        with with_keys(''):
            executor = self.migrate_to(
                [('deploying', '0002_encrypt_hosting_secrets')],
            )
        new_apps = executor.loader.project_state(
            [('deploying', '0002_encrypt_hosting_secrets')],
        ).apps
        New = new_apps.get_model('deploying', 'HostingProfile')
        row = New.objects.get(name='Без ключа')
        self.assertFalse(is_encrypted(row.secret_encrypted))
        with self.assertLogs('secretstore.crypto', level='WARNING'):
            self.assertEqual(
                decrypt(row.secret_encrypted,
                        context=f'deploying.hostingprofile:{row.secret_token}:secret'),
                'пароль-без-ключа',
            )