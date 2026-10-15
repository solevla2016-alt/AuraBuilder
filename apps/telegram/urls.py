"""Маршруты Telegram Mini App (ТЗ п.16.6)."""

from __future__ import annotations

from django.urls import path

from .api import (
    telegram_auth,
    telegram_bot_detail,
    telegram_bot_menu,
    telegram_bots,
)
from .views import mini_app

urlpatterns = [
    path('api/projects/<str:project_id>/telegram-bot/',
         telegram_bots, name='telegram-bots'),
    path('api/projects/<str:project_id>/telegram-bot/<str:bot_id>/',
         telegram_bot_detail, name='telegram-bot'),
    path('api/projects/<str:project_id>/telegram-bot/<str:bot_id>/menu/',
         telegram_bot_menu, name='telegram-bot-menu'),
    path('api/telegram/auth/', telegram_auth, name='telegram-auth'),
    # Публичная Mini App. Объявлена под своим префиксом, чтобы адрес
    # бота не путался с адресами платформы.
    path('telegram/<str:bot_username>/', mini_app, name='telegram-mini-app'),
]