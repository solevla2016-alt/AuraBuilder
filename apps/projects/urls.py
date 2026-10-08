"""Маршруты приложения projects.

Подключается под api/projects/, поэтому здесь только маршруты проектов.
Каталог модулей лежит выше — на api/modules/ — он общий для редактора
и всех проектов. Регистрируется в controlplane/urls.py.

Участники и журнал объявлены раньше деталей проекта: иначе строка
'members' разбиралась бы как project_id.
"""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.project_list, name='project-list'),
    path('<str:project_id>/members/', views.project_members, name='project-members'),
    path('<str:project_id>/audit/', views.audit_log, name='project-audit'),
    # Версии объявлены раньше деталей проекта: иначе строка «versions»
    # разбиралась бы как project_id.
    path('<str:project_id>/versions/', views.version_list, name='project-versions'),
    # Экспорт объявлен раньше деталей: иначе строка 'export'
    # разбиралась бы как project_id.
    path('<str:project_id>/export/', views.project_export, name='project-export'),
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