"""Модели биллинга: подписка и тарифные ограничения (ТЗ п.17.1)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .plans import DEFAULT_PLAN, PLANS, Plan, get_plan


class Subscription(models.Model):
    """Подписка пользователя на тариф.

    Хранится одна строка на пользователя. Понижение тарифа может быть
    отложенным: если новый тариф меньше по лимитам, а лимиты уже
    превышены, публикация новых страниц блокируется, но уже
    опубликованные страницы продолжают работать. Это требование ТЗ
    («превышение лимитов блокирует публикацию новых страниц»), и
    именно поэтому тариф меняется, а не отменяется.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscription',
        verbose_name='пользователь',
    )
    plan = models.CharField(
        max_length=16,
        choices=[(code, plan.title) for code, plan in PLANS.items()],
        default=DEFAULT_PLAN,
        verbose_name='тариф',
    )
    pending_plan = models.CharField(
        max_length=16,
        choices=[(code, plan.title) for code, plan in PLANS.items()],
        blank=True,
        default='',
        verbose_name='отложенный тариф',
    )
    pending_since = models.DateTimeField(
        null=True, blank=True, verbose_name='отложенный тариф с',
    )
    active = models.BooleanField(default=True, verbose_name='активна')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='создана')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='обновлена')

    class Meta:
        verbose_name = 'подписка'
        verbose_name_plural = 'подписки'

    def __str__(self) -> str:
        return f'{self.user} — {self.plan}'

    @property
    def effective_plan(self) -> Plan:
        """Тариф, действующий сейчас: отложенный включается после суток.

        ТЗ требует, чтобы смена тарифа применялась в течение суток.
        Раньше суток изменения не видно, поэтому `pending_plan` не
        влияет на лимиты; после — влияет, и его можно свернуть в
        `plan` при следующем чтении.
        """
        if self.pending_plan and self.pending_since:
            deadline = self.pending_since + timezone.timedelta(days=1)
            if timezone.now() >= deadline:
                return get_plan(self.pending_plan)
        return get_plan(self.plan)

    def apply_pending_if_due(self) -> bool:
        """Свернуть отложенный тариф в основной, когда срок вышел."""
        if not self.pending_plan or not self.pending_since:
            return False
        if timezone.now() < self.pending_since + timezone.timedelta(days=1):
            return False
        self.plan = self.pending_plan
        self.pending_plan = ''
        self.pending_since = None
        self.save(update_fields=['plan', 'pending_plan', 'pending_since',
                                 'updated_at'])
        return True


__all__ = ['Subscription']