"""Секреты в моделях: прозрачное шифрование при записи и чтении.

Знание о том, что поле зашифровано, не должно размазываться по
приложению: модели знают про `set_secret` и `get_secret`, а код, который
работает с секретом, не знает, лежит он в базе открытым или закрытым.
"""

from __future__ import annotations

from .crypto import (
    SecretsUnavailable,
    decrypt,
    encrypt,
    is_encrypted,
    reencrypt,
)


def secret_context(instance, field: str) -> str:
    """Контекст шифрования: модель и её запись.

    Запись опознаётся собственным токеном, а не первичным ключом:
    токен известен до сохранения, поэтому секрет можно зашифровать при
    создании объекта, и шифротекст нельзя перенести в другую запись —
    AES-GCM проверит подмену при чтении.
    """
    token = getattr(instance, 'secret_token', '') or getattr(instance, 'pk', '')
    return f'{instance._meta.label_lower}:{token}:{field}'


class SecretMixin:
    """Модель, у которой есть шифруемое поле.

    Поле в базе называется `<field>_encrypted`. Поле `set_<field>`
    принимает открытое значение, `get_<field>` возвращает открытое же.
    """

    #: Имя поля с шифротекстом.
    secret_encrypted_field = 'secret_encrypted'

    def set_secret(self, plaintext: str, *, field: str = 'secret') -> None:
        """Записывает секрет, шифруя его активным ключом."""
        if plaintext == '':
            setattr(self, self.secret_encrypted_field, '')
            return
        context = secret_context(self, field)
        setattr(self, self.secret_encrypted_field, encrypt(plaintext,
                                                            context=context))

    def get_secret(self, *, field: str = 'secret') -> str:
        """Читает секрет, расшифровывая его."""
        blob = getattr(self, self.secret_encrypted_field, '') or ''
        if blob == '':
            return ''
        return decrypt(blob, context=secret_context(self, field))

    def has_secret(self, *, field: str = 'secret') -> bool:
        return bool(getattr(self, self.secret_encrypted_field, ''))

    def secret_is_encrypted(self, *, field: str = 'secret') -> bool:
        return is_encrypted(getattr(self, self.secret_encrypted_field, '') or '')

    def rotate_secret(self, *, field: str = 'secret') -> bool:
        """Перешифровывает секрет активным ключом. True — изменилось."""
        blob = getattr(self, self.secret_encrypted_field, '') or ''
        if blob == '':
            return False
        context = secret_context(self, field)
        updated = reencrypt(blob, context=context)
        if updated != blob:
            setattr(self, self.secret_encrypted_field, updated)
        return updated != blob


__all__ = ['SecretMixin', 'SecretsUnavailable', 'secret_context']