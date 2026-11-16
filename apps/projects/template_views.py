"""Шаблоны страниц и блоков проекта (этап 2).

Шаблон — снимок, а не ссылка: правка страницы после сохранения шаблона
его не меняет. Иначе «удачным решением» оказалось бы текущее состояние,
а не то, которое человек выбрал.

Шаблоны принадлежат проекту, а не пользователю: блоки могут ссылаться
на источники данных и файлы медиатеки этого проекта. Перенос в другой
проект потребовал бы переписывать ссылки, и делать вид, что шаблон
работает, нельзя.
"""

from __future__ import annotations

import copy
import uuid

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import (
    EDIT_CONTENT,
    VIEW,
    IsAuthenticatedUser,
    can,
)
from accounts.serializers import audit

from .models import (
    MAX_TEMPLATES,
    TEMPLATE_BLOCK,
    TEMPLATE_KIND_CHOICES,
    TEMPLATE_PAGE,
    Page,
    Project,
    Template,
)

KIND_VALUES = {value for value, _label in TEMPLATE_KIND_CHOICES}


def _project_by_id(project_id: str) -> Project | None:
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, AttributeError, TypeError):
        return None


def _page_or_none(project: Project, raw) -> Page | None:
    """Дополнительная страница по идентификатору. None — главная.

    Главная не лежит в Page: её дерево хранится в самом проекте.
    """
    if raw in (None, ''):
        return None
    try:
        page_id = uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None
    return project.pages.filter(pk=page_id).first()


def _find_block(tree: dict, block_id: str) -> dict | None:
    """Блок верхнего уровня по идентификатору.

    Модули не вкладываются друг в друга, поэтому обход в глубину не
    нужен: дерево — плоский список блоков.
    """
    if not isinstance(tree, dict):
        return None
    for block in tree.get('blocks', []):
        if isinstance(block, dict) and block.get('id') == block_id:
            return block
    return None


def _page_meta(project: Project, page: Page | None) -> dict:
    if page is None:
        return {
            'title': project.name,
            'slug': '',
            'seoTitle': '',
            'seoDescription': '',
        }
    return {
        'title': page.title,
        'slug': page.slug,
        'seoTitle': page.seo_title,
        'seoDescription': page.seo_description,
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def template_list(request, project_id: str):
    """Список шаблонов проекта и сохранение нового."""

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response({
            'templates': [
                item.public_dict() for item in project.templates.all()
            ],
            'limit': MAX_TEMPLATES,
        })

    if not can(request.user, project, EDIT_CONTENT):
        return Response(
            {'detail': 'Сохранять шаблоны может тот, кто редактирует проект.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    name = str(body.get('name') or '').strip()
    if not name:
        return Response(
            {'detail': 'Укажите название шаблона.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(name) > 120:
        return Response(
            {'detail': 'Название шаблона — не длиннее 120 символов.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    kind = body.get('kind') or TEMPLATE_PAGE
    if kind not in KIND_VALUES:
        return Response({'detail': 'Неизвестный вид шаблона.'},
                        status=status.HTTP_400_BAD_REQUEST)

    page = _page_or_none(project, body.get('page'))
    if body.get('page') not in (None, '') and page is None:
        return Response({'detail': 'страница не найдена'},
                        status=status.HTTP_404_NOT_FOUND)

    if kind == TEMPLATE_PAGE:
        source = page.tree if page is not None else project.tree
        tree = copy.deepcopy(source)
        meta = _page_meta(project, page)
    else:
        # Блок можно взять и с главной: её дерево лежит в проекте, а не
        # в Page. Требовать «выберите страницу» значило бы запретить
        # сохранять блоки с самой первой страницы сайта.
        source_tree = page.tree if page is not None else project.tree
        block_id = str(body.get('block') or '').strip()
        block = _find_block(source_tree, block_id)
        if block is None:
            return Response({'detail': 'блок не найден'},
                            status=status.HTTP_404_NOT_FOUND)
        tree = copy.deepcopy(block)
        meta = {
            'title': page.title if page is not None else project.name,
            'module': block.get('module', ''),
            'label': block.get('label', ''),
        }

    if project.templates.count() >= MAX_TEMPLATES:
        return Response(
            {'detail': f'Достигнут предел шаблонов ({MAX_TEMPLATES}): '
                       'удалите ненужные.'},
            status=status.HTTP_409_CONFLICT,
        )

    template = Template.objects.create(
        project=project,
        kind=kind,
        name=name,
        tree=tree,
        meta=meta,
        created_by=request.user,
    )
    audit(request, 'template.create', project, f'{kind}: {name}')
    return Response(template.public_dict(detail=True),
                    status=status.HTTP_201_CREATED)


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def template_detail(request, project_id: str, template_id: str):
    """Содержимое шаблона и удаление."""

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    try:
        template_uuid = uuid.UUID(template_id)
    except (ValueError, AttributeError, TypeError):
        return Response({'detail': 'шаблон не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    template = project.templates.filter(pk=template_uuid).first()
    if template is None:
        return Response({'detail': 'шаблон не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(template.public_dict(detail=True))

    if not can(request.user, project, EDIT_CONTENT):
        return Response(
            {'detail': 'Удалять шаблоны может тот, кто редактирует проект.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    audit(request, 'template.delete', project, template.name)
    template.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
