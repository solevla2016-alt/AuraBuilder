"""Приложение Telegram Mini App (ТЗ п.16.6)."""

from __future__ import annotations

from django.apps import AppConfig


class TelegramConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'telegram'
    verbose_name = 'Telegram Mini App'