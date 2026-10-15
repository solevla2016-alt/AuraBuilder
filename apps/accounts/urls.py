"""Маршруты аутентификации и управления доступом (ТЗ п.11.1).

Пути начинаются с /api/auth/, чтобы отличать их от пользовательских
данных проектов: вход — это единственное место, куда можно ходить
без токена.
"""

from django.urls import path

from . import recovery, views

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
    # Восстановление пароля и удаление аккаунта (ТЗ п.13.1).
    path('password-reset/request/',
         recovery.PasswordResetRequestView.as_view(),
         name='password-reset-request'),
    path('password-reset/confirm/',
         recovery.PasswordResetConfirmView.as_view(),
         name='password-reset-confirm'),
    path('me/delete/',
         recovery.AccountDeleteView.as_view(),
         name='account-delete'),
]

