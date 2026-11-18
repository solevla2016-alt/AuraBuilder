"""Маршруты Академии. Подключаются в controlplane/urls.py под /api/."""

from django.urls import path

from . import views

urlpatterns = [
    path('academy/', views.lesson_list, name='academy-lessons'),
    path(
        'academy/<str:lesson_id>/complete/',
        views.lesson_progress,
        name='academy-lesson-progress',
    ),
]
