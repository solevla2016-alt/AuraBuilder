"""Маршруты приложения projects.

Подключается под api/projects/, поэтому здесь только маршруты проектов.
Каталог модулей лежит выше — на api/modules/ — он общий для редактора
и всех проектов. Регистрируется в controlplane/urls.py.

Участники и журнал объявлены раньше деталей проекта: иначе строка
'members' разбиралась бы как project_id.
"""

from django.urls import path

from . import views
from .config_views import project_config_export, project_config_import
from .review_views import (
    project_comment_detail,
    project_comments,
    project_review,
)
from .template_views import template_detail, template_list

urlpatterns = [
    path('', views.project_list, name='project-list'),
    # Импорт объявлен раньше <str:project_id>: иначе строка 'import'
    # разбиралась бы как идентификатор проекта.
    path('import/', project_config_import, name='project-config-import'),
    path('<str:project_id>/pages/', views.page_list, name='project-pages'),
    path(
        '<str:project_id>/pages/<str:page_id>/',
        views.page_detail,
        name='project-page-detail',
    ),
    # Шаблоны страниц и блоков: снимки удачных решений внутри проекта.
    # Лежат рядом со страницами, потому что их источник — страница.
    path('<str:project_id>/templates/', template_list, name='project-templates'),
    path(
        '<str:project_id>/templates/<str:template_id>/',
        template_detail,
        name='project-template-detail',
    ),
    # Ревью-режим: статус согласования и замечания к страницам и блокам.
    path('<str:project_id>/review/', project_review, name='project-review'),
    path(
        '<str:project_id>/comments/',
        project_comments,
        name='project-comments',
    ),
    path(
        '<str:project_id>/comments/<str:comment_id>/',
        project_comment_detail,
        name='project-comment-detail',
    ),
    path('<str:project_id>/members/', views.project_members, name='project-members'),
    path('<str:project_id>/audit/', views.audit_log, name='project-audit'),
    path('<str:project_id>/events/', views.project_events, name='project-events'),
    # Версии объявлены раньше деталей проекта: иначе строка «versions»
    # разбиралась бы как project_id.
    path('<str:project_id>/versions/', views.version_list, name='project-versions'),
    # Экспорт объявлен раньше деталей: иначе строка 'export'
    # разбиралась бы как project_id.
    path('<str:project_id>/export/', views.project_export, name='project-export'),
    # Конфигурация проекта (ТЗ п.16.7): тоже двухуровневая, как выгрузка.
    path(
        '<str:project_id>/config/',
        project_config_export,
        name='project-config-export',
    ),
    path(
        '<str:project_id>/versions/<int:number>/',
        views.version_detail,
        name='project-version-detail',
    ),
    path(
        '<str:project_id>/versions/<int:number>/restore/',
        views.version_restore,
        name='project-version-restore',
    ),
    path('<str:project_id>/', views.project_detail, name='project-detail'),
]