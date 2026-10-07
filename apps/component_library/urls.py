"""Маршруты библиотеки компонентов.

Подключаются в controlplane/urls.py:

    /api/projects/<id>/component-styles/          — стили проекта
    /api/projects/<id>/component-styles/<kind>/   — стиль одного вида
"""

from django.urls import path

from . import views

urlpatterns = [
    path(
        'projects/<str:project_id>/component-styles/',
        views.style_list,
        name='component-style-list',
    ),
    path(
        'projects/<str:project_id>/component-styles/<str:kind>/',
        views.style_detail,
        name='component-style-detail',
    ),
]
