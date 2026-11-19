"""Маршруты вебхуков.

Подключаются в controlplane/urls.py под /api/ до маршрутов проектов:
путь projects/<id>/webhooks/ должен разбираться здесь, а не как
неизвестный подресурс проекта.
"""

from django.urls import path

from . import views

urlpatterns = [
    path(
        'projects/<str:project_id>/webhooks/',
        views.webhook_list,
        name='project-webhooks',
    ),
    path(
        'projects/<str:project_id>/webhooks/<str:webhook_id>/',
        views.webhook_detail,
        name='project-webhook-detail',
    ),
    path(
        'projects/<str:project_id>/webhooks/<str:webhook_id>/rotate/',
        views.webhook_rotate,
        name='project-webhook-rotate',
    ),
    path(
        'projects/<str:project_id>/webhooks/<str:webhook_id>/'
        'deliveries/<str:delivery_id>/retry/',
        views.delivery_retry,
        name='project-webhook-retry',
    ),
]
