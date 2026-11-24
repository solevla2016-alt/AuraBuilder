"""ИИ-помощник по структуре проекта: генерация и подсказки."""

from __future__ import annotations

from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assistant'
    verbose_name = 'ИИ-помощник'
