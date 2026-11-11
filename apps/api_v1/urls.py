"""Маршруты публичного API v1.

Порядок: статические сегменты раньше динамических. Идентификатор
проекта — строка, а не UUID-конвертер: неверный формат должен давать
наш 404 в общем конверте, а не страницу ошибки Django.
"""

from django.urls import path

from . import mcp_views, views

urlpatterns = [
    path('', views.index, name='api-v1-index'),
    path('mcp/', mcp_views.mcp_endpoint, name='api-v1-mcp'),
    path('projects/', views.project_list, name='api-v1-projects'),
    path(
        'projects/<str:project_id>/',
        views.project_detail,
        name='api-v1-project',
    ),
    path(
        'projects/<str:project_id>/pages/',
        views.page_list,
        name='api-v1-pages',
    ),
    path(
        'projects/<str:project_id>/pages/<str:slug>/',
        views.page_detail_view,
        name='api-v1-page',
    ),
    path(
        'projects/<str:project_id>/versions/',
        views.version_list,
        name='api-v1-versions',
    ),
    path(
        'projects/<str:project_id>/export/',
        views.project_export,
        name='api-v1-export',
    ),
]
