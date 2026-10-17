"""Маршруты медиатеки проекта."""

from __future__ import annotations

from django.urls import path

from .api import asset_detail, asset_file, assets

urlpatterns = [
    path('api/projects/<str:project_id>/assets/', assets, name='assets'),
    path('api/projects/<str:project_id>/assets/<str:asset_id>/',
         asset_detail, name='asset-detail'),
    # Имя файла содержит точку и дефис: <str:> их пропускает.
    path('api/projects/<str:project_id>/assets/<str:name>/file/',
         asset_file, name='asset-file'),
]
