"""Проверка прав по тарифу (ТЗ п.17.1).

Правила тарификации собраны здесь, а не в представлениях: одно место
решает, что разрешено, и одно место отвечает на вопрос «почему нет».
Представление, ограничивающее себя, заканчивается тем, что половина
приложения обходит проверку, а пользователь видит разные правила в
разных сценариях.

В self-hosted тарифов нет (BILLING_ENABLED=False): установка уже
принадлежит заказчику, и продавать ему место внутри его же сервера
незачем. Проверки в этом режиме разрешают всё, но технические лимиты
из settings.LIMITS остаются — они защищают платформу, а не тариф.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from data_sources.models import DataRecord
from projects.models import Page, Project

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
    """Тариф пользователя; без подписки — Free.

    В self-hosted возвращается Business: это не «щедрость», а
    отсутствие шкалы. Иначе владелец установки увидел бы в интерфейсе
    Free и упёрся в лимит одного проекта на собственном сервере.
    """
    if not settings.BILLING_ENABLED:
        return get_plan('business')
    subscription = getattr(user, 'subscription', None)
    if subscription is None or not subscription.active:
        return get_plan('free')
    return subscription.effective_plan


def check_scenario(user, scenario: int) -> Denial | None:
    """Разрешён ли сценарий тарифом. None — разрешён."""
    if not settings.BILLING_ENABLED:
        return None
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


def usage_for(user) -> dict[str, int]:
    """Сколько места занято на тарифе прямо сейчас.

    Считается по владельцу проекта, как и проверки лимитов: участие в
    чужом проекте не тратит место плательщика, иначе приглашённый
    редактор на Free занимал бы чужую квоту.

    Главная страница живёт в Project.tree, а не в Page, поэтому к числу
    дополнительных страниц прибавляется число проектов. Без этого
    проект с одной главной показывал бы «0 страниц» и лимит страниц
    никогда не срабатывал бы на первом шаге.
    """
    projects = Project.objects.filter(owner=user).count()
    pages = Page.objects.filter(project__owner=user).count() + projects
    records = DataRecord.objects.filter(source__project__owner=user).count()
    return {'projects': projects, 'pages': pages, 'records': records}


def published_projects(user) -> int:
    """Сколько проектов пользователя опубликовано.

    Нужен не для лимитов, а для первого экрана: пока сайтов нет,
    человеку полезнее подсказка «опубликуйте», чем статистика.
    Отозванный сайт не считается: его по-прежнему нельзя показать.
    """
    return Project.objects.filter(owner=user, site__state='active').count()


def quota_row(used: int, limit: int | None) -> dict[str, int | None]:
    """Пара «занято/предел» для интерфейса.

    None в limit означает «без ограничения», а не «ноль»: интерфейс
    обязан различать эти случаи, иначе Business показывал бы полосу,
    заполненную на 100% при любом числе проектов.
    """
    return {'used': used, 'limit': limit}


def check_project_slot(user) -> Denial | None:
    """Можно ли создать ещё один проект."""
    if not settings.BILLING_ENABLED:
        return None
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
    if not settings.BILLING_ENABLED:
        return None
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
    if not settings.BILLING_ENABLED:
        return None
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
    'published_projects',
    'quota_row',
    'usage_for',
]