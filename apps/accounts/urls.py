"""Маршруты аутентификации и управления доступом (ТЗ п.11.1).

Пути начинаются с /api/auth/, чтобы отличать их от пользовательских
данных проектов: вход — это единственное место, куда можно ходить
без токена.
"""

from django.urls import path

from . import views

urlpatterns = [
    # Регистрация и вход
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('refresh/', views.RefreshView.as_view(), name='token-refresh'),
    path('logout/', views.LogoutView.as_view(), name='logout'),

    # Профиль и согласие на обработку ПДн
    path('me/', views.MeView.as_view(), name='me'),
    path('consent/', views.ConsentView.as_view(), name='consent'),

    # Заглушка подтверждения email: заработает вместе с этапом 8.
    path('confirm-email/', views.RegisterKeyView.as_view(), name='confirm-email'),
]