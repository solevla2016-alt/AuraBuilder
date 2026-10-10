"""Права доступа (ТЗ п.11.1).

Матрица ролей собрана в одном месте не для красоты: раньше права
размазаны по представлениям, и добавление роли означало бы правку в
каждом эндпоинте. Здесь роль раскладывается на конкретные действия, а
представления спрашивают только действие.

Правила, которые стоит знать до правки:

* Неизвестная роль не даёт прав. По умолчанию доступ запрещён —
  иначе опечатка в значении роли тихо превратила бы Viewer в Owner.
* Владелец проекта всегда Owner, даже если запись в таблице участников
  говорит иначе: потерять владельца проекта нельзя.
* Проверка идёт по проекту, к которому обращается запрос, а не по
  факту входа: пользователь может иметь доступ к десяти проектам и
  не иметь доступа к одиннадцатому.
"""

from __future__ import annotations

from typing import Iterable

from django.db.models import Q, QuerySet
from rest_framework import permissions

from .models import Membership, Role

# Сообщение о превышении технического лимита (ТЗ п.4.11). Одно на все
# случаи: пользователю важно само число и граница, а не то, какой
# именно слой превысил лимит.
LIMIT_ERROR = (
    "Превышен технический лимит: {what} {count}, максимум {limit}. "
    "Лимит снизить нельзя — сократите содержимое."
)

# Действия, на которые разбираются права. Строки используются и в
# журнале (ТЗ п.11.2), поэтому они короткие и стабильные.
VIEW = 'view'
EDIT_CONTENT = 'edit_content'
EDIT_SETTINGS = 'edit_settings'
PUBLISH = 'publish'
MANAGE_INTEGRATIONS = 'manage_integrations'
MANAGE_BILLING = 'manage_billing'
DELETE = 'delete'
MANAGE_ACCESS = 'manage_access'


#: Что умеет каждая роль. Владелец получает всё, но перечислен явно:
#: неявное «всё остальное» означало бы, что новое действие достанется
#: владельцу автоматически, даже если оно не входит в ТЗ п.11.1.
ROLE_ACTIONS: dict[str, frozenset[str]] = {
    Role.VIEWER: frozenset({VIEW}),
    Role.EDITOR: frozenset({VIEW, EDIT_CONTENT}),
    Role.DEV: frozenset({VIEW, EDIT_CONTENT, MANAGE_INTEGRATIONS}),
    Role.ADMIN: frozenset(
        {VIEW, EDIT_CONTENT, EDIT_SETTINGS, PUBLISH, MANAGE_INTEGRATIONS}
    ),
    Role.OWNER: frozenset(
        {
            VIEW,
            EDIT_CONTENT,
            EDIT_SETTINGS,
            PUBLISH,
            MANAGE_INTEGRATIONS,
            MANAGE_BILLING,
            DELETE,
            MANAGE_ACCESS,
        }
    ),
}


def actions_for(role: str | None) -> frozenset[str]:
    """Действия роли. Неизвестная роль — пустой набор."""
    return ROLE_ACTIONS.get(role or '', frozenset())


def has_action(role: str | None, action: str) -> bool:
    return action in actions_for(role)


def project_role(user, project) -> str | None:
    """Роль пользователя в проекте либо None.

    Порядок важен: сначала владелец. Владелец есть и в таблице
    участников, но проверяется отдельно — если запись окажется удалена,
    проект всё равно должен оставаться управляемым.
    """
    if not user or not user.is_authenticated:
        return None
    if project.owner_id == user.id:
        return Role.OWNER
    membership = Membership.objects.filter(project=project, user=user).only('role').first()
    return membership.role if membership else None


def can(user, project, action: str) -> bool:
    return has_action(project_role(user, project), action)


def readable_projects(user) -> QuerySet:
    """Проекты, которые пользователь может открыть.

    Условие «владелец ИЛИ участие» повторяется ещё в нескольких
    местах, поэтому оно живёт здесь одной строкой.
    """
    from projects.models import Project

    return Project.objects.filter(
        Q(owner=user) | Q(memberships__user=user)
    ).distinct()


def writable_projects(user) -> QuerySet:
    """Проекты, в которых пользователю можно менять содержимое."""
    roles = [r for r, actions in ROLE_ACTIONS.items() if EDIT_CONTENT in actions]
    return Project.objects.filter(
        Q(owner=user) | Q(memberships__user=user, memberships__role__in=roles)
    ).distinct()


class IsAuthenticatedUser(permissions.BasePermission):
    """Требует входа.

    Стандартный IsAuthenticated не годится: он пропускает и
    IsActive, но не проверяет, что запрос действительно аутентифицирован,
    если REST_FRAMEWORK настроен на AllowAny. Явная проверка читается
    однозначно и не зависит от настроек по умолчанию.
    """

    message = 'Требуется вход в систему.'

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)


class ProjectAccess(permissions.BasePermission):
    """Доступ к проекту по роли.

    Действие берётся у представления (view.action или атрибут
    required_action), поэтому набор проверок в одном месте.
    """

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        action = getattr(view, 'required_action', None)
        if action is None:
            action = ACTION_BY_METHOD.get(request.method, VIEW)
        return can(request.user, obj, action)


#: Какому действию соответствует метод, если представление не задало
#: своё. Чтение списка детально не означает права менять.
ACTION_BY_METHOD = {
    'GET': VIEW,
    'HEAD': VIEW,
    'OPTIONS': VIEW,
    'POST': EDIT_CONTENT,
    'PUT': EDIT_CONTENT,
    'PATCH': EDIT_CONTENT,
    'DELETE': DELETE,
}


def roles_with(action: str) -> Iterable[str]:
    return [role for role, actions in ROLE_ACTIONS.items() if action in actions]