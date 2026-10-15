"""Проверка прав по тарифу (ТЗ п.17.1).

Правила тарификации собраны здесь, а не в представлениях: одно место
решает, что разрешено, и одно место отвечает на вопрос «почему нет».
Представление, ограничивающее себя, заканчивается тем, что половина
приложения обходит проверку, а пользователь видит разные правила в
разных сценариях.
"""

from __future__ import annotations

from dataclasses import dataclass

from projects.models import Project

from .plans import Plan, get_plan

#: Понятные названия сценариев для сообщений пользователю.
SCENARIO_TITLES = {
    1: 'публикация сайта',
    2: 'выгрузка в статику',
    3: 'one-click deploy',
    4: 'Telegram и PWA',
    5: 'JSON-бэкап проекта',
}

#: Минимальный тариф для каждого тарифицируемого сценария.
SCENARIO_MINIMUM = {
    2: 'start',
    3: 'start',
    4: 'pro',
}


@dataclass(frozen=True)
class Denial:
    """Отказ в праве: причина, пригодная для показа пользователю."""

    reason: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def plan_for(user) -> Plan:
    """Тариф пользователя; без подписки — Free."""
    subscription = getattr(user, 'subscription', None)
    if subscription is None or not subscription.active:
        return get_plan('free')
    return subscription.effective_plan


def check_scenario(user, scenario: int) -> Denial | None:
    """Разрешён ли сценарий тарифом. None — разрешён."""
    plan = plan_for(user)
    if plan.allows(scenario):
        return None
    minimum = get_plan(SCENARIO_MINIMUM.get(scenario, 'business'))
    title = SCENARIO_TITLES.get(scenario, 'сценарий')
    return Denial(
        reason='tariff_denied',
        detail=(
            f'Сценарий «{title}» доступен с тарифа '
            f'{minimum.title} ({minimum.price} ₽/мес). '
            f'Текущий тариф — {plan.title}.'
        ),
    )


def check_project_slot(user) -> Denial | None:
    """Можно ли создать ещё один проект."""
    plan = plan_for(user)
    if plan.max_projects is None:
        return None
    count = Project.objects.filter(owner=user).count()
    if count < plan.max_projects:
        return None
    return Denial(
        reason='project_limit',
        detail=(
            f'На тарифе {plan.title} можно держать '
            f'{plan.max_projects} проект(ов). Сейчас уже {count}. '
            f'Освободите место или перейдите на тариф выше.'
        ),
    )


def check_page_slot(user, pages: int) -> Denial | None:
    """Можно ли разместить столько страниц (одна страница = одно дерево).

    Проект в платформе — это одно дерево, поэтому «страницы» считаются
    по деревьям пользователя, а не по блокам: блоки — единица
    редактирования, страница — единица публикации, и лимит в ТЗ
    задан в страницах.
    """
    plan = plan_for(user)
    if plan.max_pages is None:
        return None
    if pages <= plan.max_pages:
        return None
    return Denial(
        reason='page_limit',
        detail=(
            f'На тарифе {plan.title} можно опубликовать '
            f'{plan.max_pages} страниц(у). Запрошено {pages}.'
        ),
    )


def check_record_count(user, records: int) -> Denial | None:
    """Можно ли разместить столько записей (строк в источниках данных)."""
    plan = plan_for(user)
    if plan.max_records is None:
        return None
    if records <= plan.max_records:
        return None
    return Denial(
        reason='record_limit',
        detail=(
            f'На тарифе {plan.title} можно хранить '
            f'{plan.max_records} записей. Сейчас {records}.'
        ),
    )


__all__ = [
    'Denial',
    'SCENARIO_MINIMUM',
    'SCENARIO_TITLES',
    'check_page_slot',
    'check_project_slot',
    'check_record_count',
    'check_scenario',
    'plan_for',
]