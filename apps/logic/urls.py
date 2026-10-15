"""Маршруты логики страницы (Logic Graph)."""

from __future__ import annotations

from django.urls import path

from .views import logic_check, logic_graph_view, logic_library

urlpatterns = [
    path('api/logic/types/', logic_library, name='logic-library'),
    path('api/projects/<str:project_id>/logic/',
         logic_graph_view, name='logic-graph'),
    path('api/projects/<str:project_id>/logic/check/',
         logic_check, name='logic-check'),
]
