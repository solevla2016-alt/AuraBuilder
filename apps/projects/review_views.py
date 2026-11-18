"""Ревью-режим: замечания к блокам и согласование до публикации.

Согласование живёт здесь, а не в публикации: статус — свойство проекта
и страницы, а публикация только спрашивает его перед сборкой. Иначе
правило «что считается согласованным» пришлось бы повторять в каждом
месте, где сайт становится доступным.

Комментарии не попадают в собранный пакет: экспорт читает дерево и
страницы, а таблица comments остаётся на платформе. Это не побочный
эффект, а условие ТЗ п.16.4 — сайт должен работать без платформы.

Читать и комментировать может Viewer. Иначе заказчик, у которого нет
прав на правку, не смог бы оставить замечание, и ревью превратилось бы
в пересказ по телефону.
"""

from __future__ import annotations

import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import (
    EDIT_CONTENT,
    PUBLISH,
    VIEW,
    IsAuthenticatedUser,
    can,
)
from accounts.serializers import audit

from .events import record as record_event
from .models import (
    REVIEW_APPROVED,
    REVIEW_CHANGES,
    REVIEW_PENDING,
    Comment,
    Page,
    Project,
    ProjectEvent,
)

#: Длина текста замечания. Ограничение не техническое: длинный текст
#: приходит из вставки чужой переписки и превращает ревью в чат.
MAX_COMMENT_LEN = 4000
#: block_id — идентификатор блока в дереве, он же ограничен на входе API.
MAX_BLOCK_ID_LEN = 64


def _project(project_id: str) -> Project | None:
    try:
        return Project.objects.filter(
            pk=uuid.UUID(project_id),
        ).select_related('review_approved_by').first()
    except (ValueError, AttributeError, TypeError):
        return None


def _page(project: Project, raw) -> tuple[Page | None, Response | None]:
    """Страница из тела запроса; None — главная (её дерево в проекте).

    Возврат пары «значение или ответ с ошибкой» вместо исключения:
    вызывающему нужно либо продолжить, либо сразу ответить, и исключение
    ради этого добавило бы обработчик на каждый вызов.
    """

    if raw in (None, '', 'main'):
        return None, None
    try:
        page = project.pages.filter(pk=uuid.UUID(str(raw))).first()
    except (ValueError, AttributeError, TypeError):
        page = None
    if page is None:
        return None, Response(
            {'detail': 'страница не найдена'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return page, None


def _target(project: Project, page: Page | None):
    return page if page is not None else project


def _status_payload(project: Project) -> dict:
    pages = list(project.pages.select_related('review_approved_by'))
    comments = project.comments.filter(resolved=False)
    counts: dict = {}
    for comment in comments.only('page_id'):
        counts[comment.page_id] = counts.get(comment.page_id, 0) + 1

    def approved_by(entity) -> str:
        return entity.review_approved_by.get_username() if entity.review_approved_by else ''

    def approved_at(entity) -> str | None:
        value = entity.review_approved_at
        return value.isoformat() if value else None

    return {
        'status': project.review_status,
        'approvedBy': approved_by(project),
        'approvedAt': approved_at(project),
        'openComments': sum(counts.values()),
        'pages': [
            {
                'id': str(page.id),
                'title': page.title,
                'slug': page.slug,
                'status': page.review_status,
                'approvedBy': approved_by(page),
                'approvedAt': approved_at(page),
                'openComments': counts.get(page.id, 0),
            }
            for page in pages
        ],
    }


def _reset_approval(entity) -> None:
    """Возвращает согласованную сущность в «нужны правки».

    Вызывается, когда после согласования появилось новое замечание:
    молча оставлять статус «согласовано» значило бы публиковать то, чего
    ревьюер не видел.
    """

    entity.review_status = REVIEW_CHANGES
    entity.review_approved_by = None
    entity.review_approved_at = None
    entity.save(update_fields=[
        'review_status', 'review_approved_by', 'review_approved_at',
        'updated_at',
    ])


def _save_status(entity, status_value: str, actor) -> None:
    entity.review_status = status_value
    if status_value == REVIEW_APPROVED:
        entity.review_approved_by = actor
        entity.review_approved_at = timezone.now()
    else:
        entity.review_approved_by = None
        entity.review_approved_at = None
    entity.save(update_fields=[
        'review_status', 'review_approved_by', 'review_approved_at',
        'updated_at',
    ])


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def project_review(request, project_id: str):
    """Статус согласования и действия ревьюера."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response(
            {'detail': 'проект не найден'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == 'GET':
        return Response(_status_payload(project))

    body = request.data or {}
    action = body.get('action')
    if action not in ('request', 'approve', 'changes'):
        return Response(
            {'detail': 'action: ожидается request, approve или changes'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    page, error = _page(project, body.get('page'))
    if error is not None:
        return error
    target = _target(project, page)
    scope = f'страница «{page.title}»' if page else f'проект «{project.name}»'

    permission = EDIT_CONTENT if action == 'request' else PUBLISH
    if not can(request.user, project, permission):
        return Response(
            {'detail': (
                'Запросить согласование может тот, кто редактирует содержимое.'
                if action == 'request'
                else 'Согласовывать и возвращать с замечаниями может тот, кто публикует.'
            )},
            status=status.HTTP_403_FORBIDDEN,
        )

    if action == 'request':
        if target.review_status == REVIEW_PENDING:
            return Response(
                {'detail': 'Уже на согласовании.'},
                status=status.HTTP_409_CONFLICT,
            )
        _save_status(target, REVIEW_PENDING, request.user)
        message = f'На согласование отправлено: {scope}.'
        audit(request, 'review.request', project, page.slug if page else '')
    elif action == 'approve':
        if target.review_status not in (REVIEW_PENDING, REVIEW_CHANGES):
            return Response(
                {'detail': 'Согласовать можно только то, что на согласовании '
                           'или вернулось с замечаниями.'},
                status=status.HTTP_409_CONFLICT,
            )
        _save_status(target, REVIEW_APPROVED, request.user)
        message = f'Согласовано: {scope}.'
        audit(request, 'review.approve', project, page.slug if page else '')
    else:
        if target.review_status != REVIEW_PENDING:
            return Response(
                {'detail': 'Вернуть с замечаниями можно только то, что на согласовании.'},
                status=status.HTTP_409_CONFLICT,
            )
        _save_status(target, REVIEW_CHANGES, request.user)
        message = f'Возвращено с замечаниями: {scope}.'
        audit(request, 'review.changes', project, page.slug if page else '')

    record_event(
        project, ProjectEvent.KIND_REVIEW, message,
        status=ProjectEvent.STATUS_INFO, actor=request.user,
    )
    return Response(_status_payload(project))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def project_comments(request, project_id: str):
    """Замечания проекта: список с фильтрами и новое замечание."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response(
            {'detail': 'проект не найден'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == 'GET':
        query = Comment.objects.filter(project=project).select_related(
            'author', 'resolved_by',
        )
        raw_page = request.query_params.get('page')
        if raw_page is not None:
            page, error = _page(project, raw_page)
            if error is not None:
                return error
            query = query.filter(page=page)
        block_id = request.query_params.get('block')
        if block_id:
            query = query.filter(block_id=block_id)
        return Response({'comments': [item.public_dict() for item in query]})

    body = request.data or {}
    text = str(body.get('text') or '').strip()
    if not text:
        return Response(
            {'detail': 'Текст замечания не может быть пустым.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(text) > MAX_COMMENT_LEN:
        return Response(
            {'detail': f'Замечание длиннее {MAX_COMMENT_LEN} символов.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    parent = None
    raw_parent = body.get('parent')
    if raw_parent:
        try:
            parent = Comment.objects.filter(
                project=project, pk=uuid.UUID(str(raw_parent)),
            ).first()
        except (ValueError, AttributeError, TypeError):
            parent = None
        if parent is None:
            return Response(
                {'detail': 'замечание, на которое отвечают, не найдено'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    page, error = _page(project, body.get('page'))
    if error is not None:
        return error

    # Ответ наследует страницу и блок родителя: иначе ответ мог бы
    # оказаться в другой ветке обсуждения, и связь потерялась бы.
    raw_block = '' if parent else str(body.get('blockId') or '').strip()
    if len(raw_block) > MAX_BLOCK_ID_LEN:
        return Response(
            {'detail': f'blockId длиннее {MAX_BLOCK_ID_LEN} символов.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if parent is not None:
        page = parent.page
        raw_block = parent.block_id

    comment = Comment.objects.create(
        project=project,
        page=page,
        block_id=raw_block,
        author=request.user,
        text=text,
        parent=parent,
    )

    target = _target(project, page)
    if target.review_status == REVIEW_APPROVED:
        _reset_approval(target)
        record_event(
            project, ProjectEvent.KIND_REVIEW,
            f'Новое замечание после согласования: '
            f'{page.title if page else project.name}.',
            status=ProjectEvent.STATUS_INFO, actor=request.user,
        )

    audit(request, 'review.comment', project, raw_block or (page.slug if page else ''))
    return Response(comment.public_dict(), status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def project_comment_detail(request, project_id: str, comment_id: str):
    """Закрытие и удаление замечания."""

    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response(
            {'detail': 'проект не найден'},
            status=status.HTTP_404_NOT_FOUND,
        )
    try:
        comment = Comment.objects.filter(
            project=project, pk=uuid.UUID(comment_id),
        ).select_related('author', 'resolved_by').first()
    except (ValueError, AttributeError, TypeError):
        comment = None
    if comment is None:
        return Response(
            {'detail': 'замечание не найдено'},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Право решать судьбу замечания — у автора и у того, кто публикует:
    # чужое замечание не должен закрывать случайный участник, иначе
    # «нужны правки» превратилось бы в формальность.
    allowed = can(request.user, project, PUBLISH) or comment.author_id == request.user.id
    if not allowed:
        return Response(
            {'detail': 'Закрыть или удалить замечание может автор или тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'DELETE':
        comment.delete()
        audit(request, 'review.comment_delete', project, comment.block_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    resolved = (request.data or {}).get('resolved')
    if not isinstance(resolved, bool):
        return Response(
            {'detail': 'resolved: ожидается true или false'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    comment.resolved = resolved
    comment.resolved_by = request.user if resolved else None
    comment.resolved_at = timezone.now() if resolved else None
    comment.save(update_fields=['resolved', 'resolved_by', 'resolved_at'])
    return Response(comment.public_dict())
