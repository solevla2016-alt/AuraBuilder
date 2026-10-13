"""Маршруты деплоя (сценарий 3, ТЗ п.16.5).

Профили хостинга и сам деплой живут под проектом: доступ к серверу
принадлежит проекту, а не аккаунту. Путь объявлен отдельным
включением, потому что маршруты длиннее и их легче спутать с
выгрузкой архива.
"""

from django.urls import path

from deploying.views import (
    hosting_profile_detail,
    hosting_profiles,
    project_deploy,
)

urlpatterns = [
    # Префикс api/ добавляет include в controlplane.urls: здесь он
    # повторён не должен быть, иначе путь станет api/api/... и любой
    # запрос будет отдавать 404 — тихо и непонятно.
    path('projects/<str:project_id>/hosting/',
         hosting_profiles, name='hosting-profiles'),
    path('projects/<str:project_id>/hosting/<str:profile_id>/',
         hosting_profile_detail, name='hosting-profile'),
    path('projects/<str:project_id>/deploy/',
         project_deploy, name='project-deploy'),
]
