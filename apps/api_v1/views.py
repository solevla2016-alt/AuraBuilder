"""Публичный API v1.

Здесь только чтение и выгрузка. Запись остаётся во внутреннем API
редактора: у неё другой темп изменений, а внешний контракт не должен
меняться вместе с каждым улучшением панели свойств.

Почему отдельное пространство имён. Внутренний `/api/` уже отдаёт
редактору форму, которую тот ожидает. Перевести его на новый контракт
значило бы одновременно править клиент, тесты и все интеграции.
Поэтому `/api/v1/` — отдельный слой поверх тех же сервисов: поведение
одно, форма ответа стабильная.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework.decorators import api_view, permission_classes

from accounts.permissions import (
    PUBLISH,
    VIEW,
    IsAuthenticatedUser,
    can,
    project_role,
    readable_projects,
)
from accounts.serializers import audit
from billing.service import check_scenario
from projects.export import ExportError
from projects.events import record
from projects.models import ProjectEvent
from projects.package import PackageTooLarge, build_archive, slugify_ascii

from .errors import api_error, api_response
from .payloads import (
    MAIN_SLUG,
    find_project,
    home_detail,
    home_summary,
    page_detail,
    page_summary,
    project_detail_payload,
    project_summary,
    version_summary,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def _pagination(request):
    """Разбор limit/offset. Возвращает (limit, offset, ошибка или None)."""

    raw_limit = request.query_params.get('limit', str(DEFAULT_LIMIT))
    raw_offset = request.query_params.get('offset', '0')
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        return 0, 0, api_error(
            'invalid_request',
            'limit и offset должны быть целыми числами.',
            400,
        )
    if limit < 1 or limit > MAX_LIMIT or offset < 0:
        return 0, 0, api_error(
            'invalid_request',
            f'limit от 1 до {MAX_LIMIT}, offset не меньше нуля.',
            400,
        )
    return limit, offset, None


def _readable_project(user, project_id):
    """Проект, если он существует и доступен, иначе None."""

    project = find_project(project_id)
    if project is None or not can(user, project, VIEW):
        return None
    return project


@api_view(['GET'])
@permission_classes([])
def index(request):
    """Описание контракта: клиент узнаёт версию и способы входа."""

    return api_response(
        {
            'apiVersion': 1,
            'service': 'AuraBuilder',
            'auth': {
                'type': 'bearer',
                'obtain': '/api/auth/login/',
                'refresh': '/api/auth/refresh/',
            },
            'endpoints': [
                {'method': 'GET', 'path': '/api/v1/projects/'},
                {'method': 'GET', 'path': '/api/v1/projects/<id>/'},
                {'method': 'GET', 'path': '/api/v1/projects/<id>/pages/'},
                {'method': 'GET', 'path': '/api/v1/projects/<id>/pages/<slug>/'},
                {'method': 'GET', 'path': '/api/v1/projects/<id>/versions/'},
                {'method': 'GET', 'path': '/api/v1/projects/<id>/export/'},
                {'method': 'POST', 'path': '/api/v1/mcp/'},
            ],
            'pagination': {
                'limit': {'default': DEFAULT_LIMIT, 'max': MAX_LIMIT},
                'offset': {'default': 0},
            },
            'mcp': {
                'endpoint': '/api/v1/mcp/',
                'transport': 'streamable-http',
                'sse': False,
            },
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def project_list(request):
    """Проекты, которые пользователь может открыть."""

    limit, offset, error = _pagination(request)
    if error is not None:
        return error

    queryset = readable_projects(request.user).prefetch_related('pages')
    total = queryset.count()
    projects = list(queryset.order_by('-updated_at')[offset:offset + limit])
    return api_response(
        {
            'data': [
                project_summary(project, project_role(request.user, project))
                for project in projects
            ],
            'meta': {'total': total, 'limit': limit, 'offset': offset},
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def project_detail(request, project_id: str):
    project = _readable_project(request.user, project_id)
    if project is None:
        return api_error('not_found', 'Проект не найден.', 404)
    return api_response(
        project_detail_payload(project, project_role(request.user, project))
    )


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def page_list(request, project_id: str):
    """Полный список страниц, включая главную.

    Главная хранится не в Page, но клиенту нужен один список: иначе
    ему пришлось бы помнить, что такое отсутствующий slug.
    """

    project = _readable_project(request.user, project_id)
    if project is None:
        return api_error('not_found', 'Проект не найден.', 404)
    pages = [home_summary(project)]
    pages.extend(page_summary(page) for page in project.pages.all())
    return api_response({'projectId': str(project.id), 'pages': pages})


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def page_detail_view(request, project_id: str, slug: str):
    project = _readable_project(request.user, project_id)
    if project is None:
        return api_error('not_found', 'Проект не найден.', 404)
    if slug == MAIN_SLUG:
        return api_response(home_detail(project))
    page = project.pages.filter(slug=slug).first()
    if page is None:
        return api_error('not_found', 'Страница не найдена.', 404)
    return api_response(page_detail(page))


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def version_list(request, project_id: str):
    """Снимки без деревьев: история нужна для выбора версии, а не для чтения."""

    project = _readable_project(request.user, project_id)
    if project is None:
        return api_error('not_found', 'Проект не найден.', 404)
    versions = project.versions.all()[:50]
    return api_response(
        {
            'projectId': str(project.id),
            'versions': [version_summary(version) for version in versions],
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def project_export(request, project_id: str):
    """Статический архив. Ограничения те же, что у кнопки «Выгрузить».

    Внешний клиент не должен получать больше прав, чем редактор:
    проверяются и роль, и тариф, и наличие сохранённой версии.
    """

    project = _readable_project(request.user, project_id)
    if project is None:
        return api_error('not_found', 'Проект не найден.', 404)
    if not can(request.user, project, PUBLISH):
        return api_error(
            'forbidden', 'Выгружать проект может тот, кто публикует.', 403,
        )

    denial = check_scenario(request.user, 2)
    if denial is not None:
        return api_error('payment_required', denial.detail, 402, reason=denial.reason)

    raw_version = request.query_params.get('version')
    if raw_version is not None:
        try:
            number = int(raw_version)
        except (TypeError, ValueError):
            return api_error('invalid_request', 'version должен быть числом.', 400)
        version = project.versions.filter(number=number).first()
        if version is None:
            return api_error('not_found', 'Версия не найдена.', 404)
    else:
        version = project.versions.order_by('-number').first()
        if version is None:
            return api_error(
                'conflict', 'Сначала сохраните проект: нечего выгружать.', 409,
            )

    wants_pwa = request.query_params.get('pwa') in ('1', 'true', 'yes')
    if wants_pwa:
        denial = check_scenario(request.user, 4)
        if denial is not None:
            return api_error(
                'payment_required', denial.detail, 402, reason=denial.reason,
            )

    try:
        built, blob = build_archive(
            project,
            version,
            base_url=request.query_params.get('baseUrl', ''),
            pwa=wants_pwa,
        )
    except PackageTooLarge as e:
        record(
            project, ProjectEvent.KIND_BUILD,
            f'Архив не собран: превышен технический лимит ({e}).',
            status=ProjectEvent.STATUS_FAILED, actor=request.user,
        )
        return api_error(
            'payload_too_large',
            f'Проект не выгружается: превышен технический лимит ({e}).',
            413,
        )
    except ExportError as e:
        record(
            project, ProjectEvent.KIND_BUILD, str(e),
            status=ProjectEvent.STATUS_FAILED, actor=request.user,
        )
        return api_error('unprocessable', str(e), 422)

    audit(request, 'project.export', project, str(version.number))
    record(
        project, ProjectEvent.KIND_BUILD,
        f'Архив собран через API: версия {version.number}, '
        f'{len(built["files"])} файлов.',
        status=ProjectEvent.STATUS_OK, actor=request.user,
    )
    response = HttpResponse(blob, content_type='application/zip')
    response['Content-Disposition'] = content_disposition_header(
        as_attachment=True,
        filename=f'{slugify_ascii(project.name)}-static.zip',
    )
    response['X-API-Version'] = '1'
    response['X-AuraBuilder-Version'] = str(version.number)
    response['X-AuraBuilder-Warnings'] = str(len(built['report'].warnings))
    response['X-AuraBuilder-PWA'] = '1' if built['pwa'] else '0'
    return response


__all__ = [
    'index',
    'page_detail_view',
    'page_list',
    'project_detail',
    'project_export',
    'project_list',
    'version_list',
]
