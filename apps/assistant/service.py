"""Один вход в помощника: проверка, провайдер, списание, журнал.

API и будущие кнопки редактора должны вызывать `run`, а не собирать
эти шаги сами: порядок важен. Сначала провайдер отвечает, и только
потом списываются кредиты — за неудачный запрос платить незачем.
"""

from __future__ import annotations

from django.conf import settings

from accounts.permissions import EDIT_CONTENT, can
from billing.service import plan_for
from data_sources.models import DataRecord
from publications.models import Site

from . import credits
from .actions import (
    ACTIONS,
    MAX_DESCRIPTION,
    MIN_DESCRIPTION,
    Action,
    get_action,
)
from .models import AiRequest
from .providers import ProviderError, get_provider, provider_info

#: Сколько последних запросов показывать в журнале расходов.
RECENT_LIMIT = 8


class InputError(ValueError):
    """Описание не подходит к действию."""


def project_context(project) -> dict:
    """Сводка проекта для модели: числа, а не содержимое.

    Наружу не уходят ни тексты страниц, ни записи клиентов. Модели
    достаточно знать размер проекта и факт публикации, чтобы не
    советовать «опубликуйте» уже опубликованному сайту.
    """
    pages = 1 + project.pages.count()
    records = DataRecord.objects.filter(
        source__project=project,
    ).count()
    site = Site.objects.filter(project=project).only('state').first()
    return {
        'project': project.name,
        'pages': pages,
        'records': records,
        'published': bool(site and site.state == 'active'),
    }


def clean_description(action: Action, raw) -> str:
    """Проверяет описание до обращения к провайдеру.

    Нижняя граница — не придирка: на «сделай красиво» нельзя ответить
    структурой, и лучше сказать об этом сразу, чем списать кредиты за
    общие слова.
    """
    text = str(raw or '').strip()
    if not action.needs_description:
        return text[:MAX_DESCRIPTION]
    if len(text) < MIN_DESCRIPTION:
        raise InputError(
            f'Опишите задачу подробнее: минимум {MIN_DESCRIPTION} символов. '
            f'Например, что за сайт и какие разделы на нём нужны.'
        )
    if len(text) > MAX_DESCRIPTION:
        raise InputError(
            f'Описание — не длиннее {MAX_DESCRIPTION} символов. '
            f'Сократите его до сути: помощник предлагает структуру, '
            f'а не пересказывает документ.'
        )
    return text


def payer_for(project, actor):
    """С кого списывать кредиты.

    Владелец проекта, а не тот, кто нажал кнопку: помощник работает на
    проект, и расход принадлежит ему. Если у старого проекта владелец
    не заполнен, списание уходит автору запроса, чтобы помощник не
    отключался из-за неполных данных.
    """
    return getattr(project, 'owner', None) or actor


def recent_requests(project, limit: int = RECENT_LIMIT) -> list[dict]:
    """Последние запросы по проекту в виде для журнала."""
    rows = (
        AiRequest.objects.filter(project=project)
        .select_related('actor')
        .only(
            'id', 'action', 'credits', 'provider', 'created_at',
            'actor__username',
        )[:limit]
    )
    return [request_payload(row) for row in rows]


def request_payload(row: AiRequest) -> dict:
    action = ACTIONS.get(row.action)
    return {
        'id': str(row.id),
        'action': row.action,
        'action_title': action.title if action else row.action,
        'credits': row.credits,
        'provider': row.provider,
        'actor': row.actor.username if row.actor else '',
        'created_at': row.created_at.isoformat(),
    }


def status(project, actor) -> dict:
    """Состояние помощника для экрана проекта."""
    payer = payer_for(project, actor)
    info = provider_info()
    balance = credits.status_for(payer)
    can_edit = can(actor, project, EDIT_CONTENT)
    actions = []
    for action in ACTIONS.values():
        affordable = (
            balance['remaining'] is None
            or balance['remaining'] >= action.cost
        )
        actions.append({
            'code': action.code,
            'title': action.title,
            'description': action.description,
            'cost': action.cost,
            'placeholder': action.placeholder,
            'needs_description': action.needs_description,
            'available': bool(can_edit and info['ready'] and affordable),
        })
    return {
        'project': {'id': str(project.id), 'name': project.name},
        'provider': info,
        'credits': balance,
        'actions': actions,
        'recent': recent_requests(project),
        'billing_enabled': settings.BILLING_ENABLED,
        'plan': plan_for(payer).title,
        'can_edit': can_edit,
        'description_limits': {
            'min': MIN_DESCRIPTION,
            'max': MAX_DESCRIPTION,
        },
    }


def actor_can_edit(user, project) -> bool:
    return can(user, project, EDIT_CONTENT)


def run(project, actor, action_code: str, description) -> dict:
    """Выполняет действие и возвращает ответ вместе с новым остатком."""
    action = get_action(action_code)
    if action is None:
        raise InputError('Неизвестное действие помощника.')

    text = clean_description(action, description)
    context = project_context(project)
    provider = get_provider()
    result = provider.generate(action, text, context)

    payer = payer_for(project, actor)
    balance = credits.spend(payer, action.cost)
    row = AiRequest.objects.create(
        user=payer,
        actor=actor,
        project=project,
        action=action.code,
        provider=result.provider,
        credits=action.cost,
        period=credits.current_period(),
        prompt=text,
        result=result.as_dict(),
    )
    return {
        'result': result.as_dict(),
        'credits': balance,
        'request': request_payload(row),
    }


__all__ = [
    'InputError',
    'ProviderError',
    'RECENT_LIMIT',
    'clean_description',
    'payer_for',
    'project_context',
    'recent_requests',
    'run',
    'status',
]
