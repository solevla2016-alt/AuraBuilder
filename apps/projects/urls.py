"""Маршруты приложения projects."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.project_list, name='project-list'),
    path('<str:project_id>/', views.project_detail, name='project-detail'),
]
