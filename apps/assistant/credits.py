"""Кредиты ИИ: остаток, списание и границы месяца.

Правила списания собраны здесь, а не в представлении: экран, API и
будущие фоновые задачи должны видеть один и тот же остаток. Если бы
проверка жила в представлении, второй вход в помощник (например, из
палитры редактора) списывал бы кредиты мимо неё.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from billing.plans import get_plan
from billing.service import plan_for


class InsufficientCredits(Exception):
    """Кредитов на действие не хватает.

    Отдельный тип, а не `Denial`: отказ по тарифу и отказ по остатку
    говорят пользователю разное. Первый — «смените тариф», второй —
    «подождите до начала месяца или смените тариф».
    """

    def __init__(self, used: int, limit: int, cost: int) -> None:
        self.used = used
        self.limit = limit
        self.cost = cost
        super().__init__(
            f'На этот месяц осталось {max(limit - used, 0)} кредитов, '
            f'а действие стоит {cost}. Кредиты обнулятся в начале '
            f'следующего месяца; больше кредитов даёт тариф выше.'
        )


def current_period(now=None) -> str:
    """Текущий период в формате ГГГГ-ММ.

    Берётся локальная дата, а не UTC: «месяц» — это календарь
    пользователя, и вечер 31-го числа не должен относиться к другому
    месяцу только из-за часового пояса сервера.
    """
    moment = now or timezone.localdate()
    return f'{moment.year:04d}-{moment.month:02d}'


def period_end(period: str | None = None) -> str:
    """Первый день следующего месяца — дата обнуления остатка."""
    value = period or current_period()
    year, month = (int(part) for part in value.split('-', 1))
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return date(year, month, 1).isoformat()


def limit_for(user) -> int | None:
    """Месячный запас кредитов по действующему тарифу.

    None означает «без ограничения»: в self-hosted тарифов нет, а на
    Business кредиты не продаются поштучно. Ноль здесь был бы ошибкой:
    он запретил бы помощника на тарифе без ограничений.
    """
    plan = plan_for(user)
    return getattr(plan, 'ai_credits', None)


def used_credits(user, period: str | None = None) -> int:
    """Сколько кредитов уже израсходовано за период."""
    from .models import CreditPeriod

    row = CreditPeriod.objects.filter(
        user=user, period=period or current_period(),
    ).only('used').first()
    return row.used if row else 0


def status_for(user, period: str | None = None) -> dict:
    """Остаток в форме, пригодной для API и интерфейса."""
    value = period or current_period()
    used = used_credits(user, value)
    limit = limit_for(user)
    remaining = None if limit is None else max(limit - used, 0)
    return {
        'used': used,
        'limit': limit,
        'remaining': remaining,
        'period': value,
        'resets_at': period_end(value),
    }


def spend(user, cost: int, period: str | None = None) -> dict:
    """Списывает кредиты и возвращает новый остаток.

    Блокировка строки пользователя нужна, чтобы два одновременных
    запроса не прочитали один и тот же остаток и не потратили его
    дважды. Списание идёт после ответа провайдера: неудачный запрос не
    должен стоить денег.
    """
    value = period or current_period()
    if cost <= 0:
        return status_for(user, value)

    from .models import CreditPeriod

    with transaction.atomic():
        # Строка пользователя как общий замок на его кредиты: отдельной
        # строки периода может ещё не быть, и блокировать нечего.
        type(user).objects.select_for_update().only('pk').get(pk=user.pk)
        row, _ = CreditPeriod.objects.get_or_create(
            user=user, period=value, defaults={'used': 0},
        )
        limit = limit_for(user)
        if limit is not None and row.used + cost > limit:
            raise InsufficientCredits(row.used, limit, cost)
        row.used += cost
        row.save(update_fields=['used', 'updated_at'])

    return status_for(user, value)


__all__ = [
    'InsufficientCredits',
    'current_period',
    'limit_for',
    'period_end',
    'spend',
    'status_for',
    'used_credits',
]
