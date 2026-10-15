"""Приложение логики страницы (Logic Graph, ТЗ п.6.4)."""

from __future__ import annotations

from django.apps import AppConfig


class LogicConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'logic'
    verbose_name = 'Логика страницы'
