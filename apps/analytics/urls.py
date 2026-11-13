"""Маршруты аналитики.

Публичный приём заявок объявлен на верхнем уровне API: форму
отправляет посетитель сайта, и в адресе не должно быть проекта —
он определяется по Referer. Сводка живёт под проектом, потому что
читает её участник проекта.
"""

from django.urls import path

from . import views

urlpatterns = [
    # Оба адреса: старые сборки форм отправляют на /api/forms без
    # косой черты, и APPEND_SLASH превратил бы POST в GET, потеряв
    # заявку. Новые собираются на /api/forms/, но ломать уже
    # опубликованные сайты нельзя.
    path('forms', views.submit_form, name='form-submit-plain'),
    path('forms/', views.submit_form, name='form-submit'),
    path(
        'projects/<str:project_id>/analytics/',
        views.project_analytics,
        name='project-analytics',
    ),
]
