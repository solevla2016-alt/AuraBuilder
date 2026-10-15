"""Приложение хранения секретов (ТЗ п.7.3, этап 7)."""

from __future__ import annotations

from django.apps import AppConfig


class SecretsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'secretstore'
    verbose_name = 'Секреты'