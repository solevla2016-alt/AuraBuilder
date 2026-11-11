"""Представление данных проекта для внешнего API.

Поля названы в camelCase: так их ждёт редактор и так же удобнее
клиентам на JavaScript. Внутренние сериализаторы менять нельзя — они
обслуживают редактор, — поэтому публичная форма описана здесь явно и
меняется только по правилам совместимости (docs/API-V1.md).
"""

from __future__ import annotations

import uuid
from typing import Any

from projects.brand import normalize_brand
from projects.models import Page, Project

MAIN_SLUG = ''


def iso(value) -> str | None:
    return value.isoformat() if value else None


def block_count(tree: Any) -> int:
    blocks = tree.get('blocks') if isinstance(tree, dict) else None
    return len(blocks) if isinstance(blocks, list) else 0


def find_project(project_id: Any) -> Project | None:
    """Проект по идентификатору либо None.

    Неверный UUID не отличается от несуществующего: клиенту всё равно
    нужен 404, а разные ответы позволяли бы перебирать идентификаторы.
    """

    try:
        return Project.objects.select_related('owner').filter(
            pk=uuid.UUID(str(project_id)),
        ).first()
    except (ValueError, AttributeError, TypeError):
        return None


def page_summary(page: Page) -> dict:
    return {
        'id': str(page.id),
        'slug': page.slug,
        'title': page.title,
        'seoTitle': page.seo_title,
        'seoDescription': page.seo_description,
        'blockCount': block_count(page.tree),
        'version': page.version,
        'updatedAt': iso(page.updated_at),
        'isHome': False,
    }


def page_detail(page: Page) -> dict:
    data = page_summary(page)
    data['tree'] = page.tree
    return data


def home_summary(project: Project) -> dict:
    """Главная страница живёт в Project.tree, а не в отдельной записи."""

    return {
        'id': None,
        'slug': MAIN_SLUG,
        'title': project.name,
        'seoTitle': '',
        'seoDescription': '',
        'blockCount': block_count(project.tree),
        'version': project.version,
        'updatedAt': iso(project.updated_at),
        'isHome': True,
    }


def home_detail(project: Project) -> dict:
    data = home_summary(project)
    data['tree'] = project.tree
    return data


def version_summary(version) -> dict:
    pages = version.pages if isinstance(version.pages, list) else []
    return {
        'number': version.number,
        'label': version.label,
        'createdAt': iso(version.created_at),
        'blockCount': block_count(version.tree),
        # Снимок хранит и главную, и дополнительные страницы. Считаем
        # их вместе: по числу видно, что версия затронула весь сайт.
        'pageCount': 1 + len(pages),
    }


def project_summary(project: Project, role: str | None) -> dict:
    return {
        'id': str(project.id),
        'name': project.name,
        'version': project.version,
        'role': role,
        'blockCount': block_count(project.tree),
        'pageCount': 1 + len(project.pages.all()),
        'createdAt': iso(project.created_at),
        'updatedAt': iso(project.updated_at),
    }


def project_detail_payload(project: Project, role: str | None) -> dict:
    data = project_summary(project, role)
    data['brand'] = normalize_brand(project.brand)
    data['tree'] = project.tree
    data['pages'] = [page_summary(page) for page in project.pages.all()]
    return data


__all__ = [
    'MAIN_SLUG',
    'block_count',
    'find_project',
    'home_detail',
    'home_summary',
    'iso',
    'page_detail',
    'page_summary',
    'project_detail_payload',
    'project_summary',
    'version_summary',
]
