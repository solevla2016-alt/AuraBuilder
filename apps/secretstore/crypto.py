"""Шифрование секретов (ТЗ п.7.3).

Платформа хранит чужие секреты: пароль доступа к серверу заказчика,
а позже — учётные данные 1С и токен бота. ТЗ п.7.3 требует AES-256
для чувствительных данных, и пароль от чужого сервера к ним относится
напрямую.

Схема — AES-256-GCM: она даёт не только конфиденциальность, но и
проверку целостности, поэтому подмена записи в базе обнаруживается
при чтении, а не при использовании.

Ключи живут в кольце (`DJANGO_SECRET_ENCRYPTION_KEYS`): первый ключ
используется для шифрования, все — для расшифровки. Это и есть
ротация: новый ключ добавляется первым, старые остаются, пока
перешифрованы данные.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

#: Префикс формата. Версия входит в значение, поэтому смена формата
#: не потребует переписывать все секреты: старые читаются своим кодом.
FORMAT = 'a1'

#: Длина ключа AES-256 — 32 байта.
KEY_BYTES = 32


class SecretsUnavailable(RuntimeError):
    """Ключа шифрования нет или он непригоден.

    Отдельный тип, чтобы вызывающий код отличал «секрет не задан» от
    «ключа нет»: в первом случае деплой идёт, во втором — нет.
    """


class SecretUnreadable(RuntimeError):
    """Секрет не расшифровался: другой ключ, подмена или порча."""


@dataclass(frozen=True)
class Key:
    """Ключ шифрования с идентификатором.

    Идентификатор пишется рядом с шифротекстом: при ротации он
    говорит, каким ключом зашифровано значение, и расшифровка идёт
    нужным ключом сразу, а не перебором.
    """

    kid: str
    material: bytes

    @classmethod
    def parse(cls, kid: str, value: str) -> 'Key':
        raw = base64.urlsafe_b64decode(value.encode('ascii'))
        if len(raw) != KEY_BYTES:
            raise SecretsUnavailable(
                f'ключ {kid}: ожидалось {KEY_BYTES} байт, получено {len(raw)}',
            )
        return cls(kid=kid, material=raw)


def _setting(name: str, default: str = '') -> str:
    try:
        from django.conf import settings
    except Exception:  # pragma: no cover - вне Django (скрипты, тесты)
        return os.environ.get(name, default)
    return getattr(settings, name, default) or default


def keyring() -> list[Key]:
    """Кольцо ключей: активный первый, остальные — для чтения.

    Пустое кольцо — не ошибка импорта, а осознанное состояние:
    платформа без ключа не хранит чужие секреты вовсе, и об этом
    сообщает вызывающий код.
    """
    raw = _setting('DJANGO_SECRET_ENCRYPTION_KEYS')
    keys: list[Key] = []
    seen: set[str] = set()
    for item in (part.strip() for part in raw.split(',')):
        if not item or ':' not in item:
            continue
        kid, _, value = item.partition(':')
        kid = kid.strip()
        if not kid or kid in seen:
            # Повтор идентификатора сделал бы ротацию непредсказуемой:
            # непонятно, какой из двух ключей активен.
            if kid:
                raise SecretsUnavailable(f'ключ {kid}: идентификатор повторяется')
            continue
        seen.add(kid)
        keys.append(Key.parse(kid, value))
    return keys


def active_key() -> Key:
    """Ключ для шифрования. Без кольца хранить секрет нечем."""
    keys = keyring()
    if not keys:
        raise SecretsUnavailable(
            'ключ шифрования не задан: задайте DJANGO_SECRET_ENCRYPTION_KEYS '
            '(идентификатор:ключ в base64url, через запятую)',
        )
    return keys[0]


def _key_by_kid(kid: str) -> Key | None:
    for key in keyring():
        if key.kid == kid:
            return key
    return None


def is_encrypted(value: str) -> bool:
    """Похоже ли значение на зашифрованный секрет."""
    return bool(value) and value.startswith(FORMAT + '.')


def encrypt(plaintext: str, *, context: str) -> str:
    """Шифрует секрет. `context` связывает значение с местом.

    Контекст (например, `hostingprofile:42`) включается в
    аутентифицируемые данные: скопировать шифротекст одного профиля в
    другой и не заметить нельзя — при чтении чужой контекст не
    совпадёт, и GCM вернёт ошибку.
    """
    if plaintext == '':
        return ''
    key = active_key()
    nonce = os.urandom(12)
    ct = AESGCM(key.material).encrypt(nonce, plaintext.encode('utf-8'),
                                      context.encode('utf-8'))
    return '.'.join([
        FORMAT,
        key.kid,
        base64.urlsafe_b64encode(nonce).decode('ascii'),
        base64.urlsafe_b64encode(ct).decode('ascii'),
    ])


def decrypt(blob: str, *, context: str) -> str:
    """Расшифровывает секрет."""
    if blob == '':
        return ''
    if not is_encrypted(blob):
        # Значение осталось незашифрованным: его видел старый этап или
        # оно введено в обход приложения. Показывать его можно, молчать
        # нельзя — иначе останется незамеченным навсегда.
        logger.warning('секрет %s хранится без шифрования', context)
        return blob
    _, kid, nonce_b64, ct_b64 = blob.split('.', 3)
    key = _key_by_kid(kid)
    if key is None:
        raise SecretUnreadable(
            f'секрет {context} зашифрован ключом {kid}, которого нет в кольце',
        )
    try:
        plain = AESGCM(key.material).decrypt(
            base64.urlsafe_b64decode(nonce_b64.encode('ascii')),
            base64.urlsafe_b64decode(ct_b64.encode('ascii')),
            context.encode('utf-8'),
        )
    except InvalidTag as e:
        raise SecretUnreadable(f'секрет {context}: неверный ключ или подмена') from e
    return plain.decode('utf-8')


def reencrypt(blob: str, *, context: str) -> str:
    """Перешифровывает секрет активным ключом.

    Возвращает то же значение, если оно уже зашифровано активным
    ключом: команда ротации должна быть безопасна при повторном запуске.
    """
    if blob == '':
        return blob
    plain = decrypt(blob, context=context)
    if is_encrypted(blob) and blob.split('.', 2)[1] == active_key().kid:
        return blob
    return encrypt(plain, context=context)


def generate_key(kid: str) -> str:
    """Новый ключ в формате окружения."""
    raw = os.urandom(KEY_BYTES)
    return f'{kid}:{base64.urlsafe_b64encode(raw).decode("ascii")}'


__all__ = [
    'FORMAT',
    'Key',
    'SecretsUnavailable',
    'SecretUnreadable',
    'active_key',
    'decrypt',
    'encrypt',
    'generate_key',
    'is_encrypted',
    'keyring',
    'reencrypt',
]