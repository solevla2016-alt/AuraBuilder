"""Модели Telegram Mini App (ТЗ п.16.6, сценарий 4A).

Бот — это способ показать проект внутри Telegram, и токен бота
принадлежит клиенту. Поэтому он хранится так же, как пароль от
сервера заказчика: зашифрованным, никогда не возвращаемым через API
(ADR-0007).
"""

from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from projects.models import Project
from secretstore.services import SecretMixin

#: Логин бота в Telegram: латиница, цифры и подчёркивание, 5–32
#: символа, заканчивается словом «bot» — это правило Telegram.
BOT_USERNAME_VALIDATOR = RegexValidator(
    regex=r'^[a-zA-Z0-9_]{5,32}$',
    message='Логин бота: 5–32 символа латиницей, цифрами и _',
)


class TelegramBot(SecretMixin, models.Model):
    """Бот, через который проект открывается как Mini App.

    Один проект может быть подключён к нескольким ботам (у клиента
    могут быть свои каналы), но логин бота уникален: адрес Mini App
    строится из него.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='telegram_bots',
        verbose_name='Проект',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_bots',
        verbose_name='Владелец',
    )
    name = models.CharField('Название', max_length=120)
    bot_username = models.CharField(
        'Логин бота', max_length=32, unique=True,
        validators=[BOT_USERNAME_VALIDATOR], db_index=True,
    )
    bot_id = models.BigIntegerField(
        'Идентификатор бота', null=True, blank=True,
        help_text='Заполняется автоматически при проверке токена',
    )
    token_encrypted = models.TextField(
        'Токен бота (шифрованный)', blank=True, default='',
        help_text='Выдаётся BotFather; хранится зашифрованным и не '
                  'возвращается через API',
    )
    # Токен привязывает шифротекст к записи (ADR-0007) и известен до
    # сохранения: шифровать иначе нечем.
    secret_token = models.UUIDField(
        'Идентификатор секрета', editable=False, default=uuid4,
    )
    menu_configured_at = models.DateTimeField(
        'Кнопка меню настроена', null=True, blank=True,
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    secret_encrypted_field = 'token_encrypted'

    class Meta:
        verbose_name = 'Telegram-бот'
        verbose_name_plural = 'Telegram-боты'
        ordering = ['name']

    def __str__(self) -> str:
        return f'@{self.bot_username}'

    @property
    def has_token(self) -> bool:
        return bool(self.token_encrypted)

    @property
    def is_menu_configured(self) -> bool:
        return self.menu_configured_at is not None

    def get_token(self) -> str:
        return self.get_secret(field='token')

    def set_token(self, token: str) -> None:
        self.set_secret(token, field='token')

    def public_dict(self) -> dict:
        """Представление для интерфейса: без токена."""
        return {
            'id': str(self.id),
            'name': self.name,
            'botUsername': self.bot_username,
            'botId': self.bot_id,
            'projectId': str(self.project_id),
            'hasToken': self.has_token,
            'menuConfigured': self.is_menu_configured,
            'menuConfiguredAt': (
                self.menu_configured_at.isoformat()
                if self.menu_configured_at else None
            ),
            'miniAppUrl': self.mini_app_url,
            'startAppLink': self.start_app_link,
        }

    @property
    def mini_app_url(self) -> str:
        """Адрес Mini App на платформе."""
        from django.conf import settings

        base = (getattr(settings, 'PLATFORM_BASE_URL', '') or '').rstrip('/')
        return f'{base}/telegram/{self.bot_username}/'

    @property
    def start_app_link(self) -> str:
        """Ссылка, которую открывают в Telegram.

        Прямая ссылка на Mini App в приложении Telegram не работает:
        Telegram показывает её как обычную страницу. Открывать надо
        через бота, поэтому в ссылке его логин и команда startapp.
        """
        return f'https://t.me/{self.bot_username}'


__all__ = ['BOT_USERNAME_VALIDATOR', 'TelegramBot']