"""Маршруты биллинга: тариф пользователя и его смена."""

from __future__ import annotations

from django.urls import path

from .api import ChangePlanView, SubscriptionView

urlpatterns = [
    path('subscription/', SubscriptionView.as_view(), name='billing-subscription'),
    path('subscription/change/', ChangePlanView.as_view(), name='billing-change'),
]