"""Маршруты ИИ-помощника. Подключаются в controlplane/urls.py под /api/.

Пути начинаются с projects/<id>/assistant/ и объявлены до общего
include проектов, иначе строка «assistant» разбиралась бы как
подресурс проекта.
"""

from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path(
        'projects/<str:project_id>/assistant/',
        views.assistant_status,
        name='assistant-status',
    ),
    path(
        'projects/<str:project_id>/assistant/run/',
        views.assistant_run,
        name='assistant-run',
    ),
]
