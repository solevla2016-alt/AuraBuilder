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
    path('<str:project_id>/', views.project_detail, name='project-detail'),
]