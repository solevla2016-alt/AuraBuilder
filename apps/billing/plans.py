"""Тарифная шкала (ТЗ п.17.1).

Тарифы описаны данными, а не ветвлениями в коде: проверка прав должна
отвечать на вопрос «что разрешено», а не «какой это номер».
Изменение шкалы при этом меняет одну таблицу, а не десять мест в
приложении.

Названия сценариев соответствуют п.16: 1 — публикация на
инфраструктуре платформы, 2 — выгрузка статики, 3 — one-click deploy,
4 — Telegram и PWA, 5 — JSON-бэкап проекта.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Сценарии, которые не тарифицируются: доступны на любом плане,
#: включая Free. Сценарий 5 — техническая гарантия сохранности
#: данных: забрать бэкап проекта можно всегда.
FREE_SCENARIOS = frozenset({1, 5})


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    price: int  # ₽ в месяц
    max_projects: int | None  # None — без ограничений
    max_pages: int | None
    max_records: int | None
    scenarios: frozenset[int]
    own_domain: bool
    cdn_priority: bool = False
    onedc_integration: bool = False

    def allows(self, scenario: int) -> bool:
        return scenario in self.scenarios


PLANS: dict[str, Plan] = {
    'free': Plan(
        code='free', title='Free', price=0,
        max_projects=1, max_pages=5, max_records=20,
        # Только технический бэкап и публикация на поддомене платформы.
        scenarios=frozenset(FREE_SCENARIOS),
        own_domain=False,
    ),
    'start': Plan(
        code='start', title='Start', price=990,
        max_projects=5, max_pages=50, max_records=500,
        scenarios=frozenset({1, 2, 3, 5}),
        own_domain=True,
    ),
    'pro': Plan(
        code='pro', title='Pro', price=2490,
        max_projects=25, max_pages=500, max_records=10_000,
        scenarios=frozenset({1, 2, 3, 4, 5}),
        own_domain=True,
        cdn_priority=True,
        onedc_integration=True,
    ),
    'business': Plan(
        code='business', title='Business', price=7990,
        max_projects=None, max_pages=None, max_records=None,
        scenarios=frozenset({1, 2, 3, 4, 5}),
        own_domain=True,
        cdn_priority=True,
        onedc_integration=True,
    ),
}

PLAN_ORDER = ('free', 'start', 'pro', 'business')

#: Тариф по умолчанию для нового пользователя и для стенда: Free.
DEFAULT_PLAN = 'free'


def get_plan(code: str) -> Plan:
    """Тариф по коду; неизвестный код трактуется как Free.

    Неизвестный код — это испорченные данные или подделка из настроек.
    Выдавать по ним права уровня Business было бы худшим ответом.
    """
    return PLANS.get((code or '').lower(), PLANS[DEFAULT_PLAN])


def rank(code: str) -> int:
    """Положение тарифа в шкале: чем больше, тем выше."""
    code = (code or '').lower()
    return PLAN_ORDER.index(code) if code in PLAN_ORDER else 0


def covers(current: str, required: str) -> bool:
    """Не ниже ли текущий тариф требуемого."""
    return rank(current) >= rank(required)


__all__ = [
    'DEFAULT_PLAN',
    'FREE_SCENARIOS',
    'PLANS',
    'PLAN_ORDER',
    'Plan',
    'covers',
    'get_plan',
    'rank',
]