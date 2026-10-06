"""Маршруты узлов данных.

Подключаются в controlplane/urls.py:

    /api/projects/<id>/data/          — источники проекта
    /api/data/<source_id>/            — источник
    /api/data/<source_id>/records/    — записи источника
    /api/data/records/<record_id>/    — запись

Отдельный префикс /api/data/ выбран потому, что записи адресуются
напрямую, без проекта, и прятать их под /api/projects/<id>/data/<src>/records/
значило бы требовать в URL идентификатор проекта, который и так есть
в ссылке источника.
"""

from django.urls import path

from . import views

urlpatterns = [
    path('projects/<str:project_id>/data/', views.source_list, name='data-source-list'),
    path('data/<str:source_id>/', views.source_detail, name='data-source-detail'),
    path('data/<str:source_id>/records/', views.record_list, name='data-record-list'),
    path('data/records/<str:record_id>/', views.record_detail, name='data-record-detail'),
]