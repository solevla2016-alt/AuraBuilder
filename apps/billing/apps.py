"""Приложение биллинга и тарифных ограничений (ТЗ п.17.1)."""

from __future__ import annotations

from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'billing'
    verbose_name = 'Тарифы и биллинг'