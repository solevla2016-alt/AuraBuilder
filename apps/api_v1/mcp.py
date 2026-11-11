"""MCP-сервер AuraBuilder: инструменты для внешних агентов.

Model Context Protocol — это JSON-RPC 2.0 поверх HTTP. Реализован
без SSE и сессий: сервер не хранит состояние между запросами, а клиент
присылает полный JSON-RPC-вызов. Такой режим (http-json) поддерживают
клиенты, которым достаточно ответа на POST, и он не требует держать
открытое соединение.

Инструменты только читают. Агент может посмотреть проект, страницы,
историю версий и сводку сборки, но не может изменить чужой сайт:
права на запись остаются у редактора, где действует ролевая модель.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from accounts.permissions import PUBLISH, VIEW, can, project_role, readable_projects
from billing.service import check_scenario
from projects.export import ExportError
from projects.package import PackageTooLarge, build_package

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

#: Версии протокола, которые понимает сервер. Порядок — от новой к
#: старой: при незнакомой версии клиента отвечаем самой новой из
#: поддерживаемых, как требует согласование MCP.
PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
LATEST_PROTOCOL = PROTOCOL_VERSIONS[0]

SERVER_INFO = {
    'name': 'aurabuilder',
    'title': 'AuraBuilder',
    'version': '1.0.0',
}

logger = logging.getLogger(__name__)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

TOOLS = [
    {
        'name': 'list_projects',
        'title': 'Список проектов',
        'description': (
            'Проекты, к которым у пользователя есть доступ: '
            'идентификатор, название, версия и размер.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {},
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_project',
        'title': 'Проект целиком',
        'description': (
            'Проект с деревом главной страницы, брендбуком и списком '
            'остальных страниц.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'projectId': {
                    'type': 'string',
                    'description': 'UUID проекта',
                },
            },
            'required': ['projectId'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'list_pages',
        'title': 'Страницы проекта',
        'description': (
            'Все страницы, включая главную (slug — пустая строка).'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'projectId': {'type': 'string'},
            },
            'required': ['projectId'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_page',
        'title': 'Страница целиком',
        'description': (
            'Одна страница с деревом блоков. Пустой slug — главная.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'projectId': {'type': 'string'},
                'slug': {
                    'type': 'string',
                    'description': 'Адрес страницы; пусто — главная',
                },
            },
            'required': ['projectId'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'list_versions',
        'title': 'История версий',
        'description': 'Последние 50 снимков проекта без деревьев.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'projectId': {'type': 'string'},
            },
            'required': ['projectId'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'export_summary',
        'title': 'Сводка сборки',
        'description': (
            'Собирает пакет и возвращает состав сборки и ссылку на '
            'скачивание архива. Может быть медленным на большом проекте.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'projectId': {'type': 'string'},
                'version': {
                    'type': 'integer',
                    'description': 'Номер версии; пусто — последняя',
                },
                'includeManifest': {
                    'type': 'boolean',
                    'description': 'Вернуть манифест сборки целиком',
                },
            },
            'required': ['projectId'],
            'additionalProperties': False,
        },
    },
]


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ToolError(Exception):
    """Ошибка выполнения инструмента: она видна агенту, но это не сбой RPC."""


def _result(request_id, result: dict) -> dict:
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _error(request_id, code: int, message: str) -> dict:
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'error': {'code': code, 'message': message},
    }


def _require_project(user, arguments: dict):
    project_id = arguments.get('projectId')
    if not isinstance(project_id, str) or not project_id:
        raise ToolError('projectId обязателен.')
    project = find_project(project_id)
    if project is None or not can(user, project, VIEW):
        raise ToolError('Проект не найден.')
    return project


def _tool_list_projects(user, arguments: dict) -> dict:
    projects = readable_projects(user).prefetch_related('pages')[:50]
    return {
        'projects': [
            project_summary(project, project_role(user, project))
            for project in projects
        ],
        'limit': 50,
    }


def _tool_get_project(user, arguments: dict) -> dict:
    project = _require_project(user, arguments)
    return project_detail_payload(project, project_role(user, project))


def _tool_list_pages(user, arguments: dict) -> dict:
    project = _require_project(user, arguments)
    pages = [home_summary(project)]
    pages.extend(page_summary(page) for page in project.pages.all())
    return {'projectId': str(project.id), 'pages': pages}


def _tool_get_page(user, arguments: dict) -> dict:
    project = _require_project(user, arguments)
    slug = arguments.get('slug', MAIN_SLUG)
    if not isinstance(slug, str):
        raise ToolError('slug должен быть строкой.')
    if slug == MAIN_SLUG:
        return home_detail(project)
    page = project.pages.filter(slug=slug).first()
    if page is None:
        raise ToolError('Страница не найдена.')
    return page_detail(page)


def _tool_list_versions(user, arguments: dict) -> dict:
    project = _require_project(user, arguments)
    versions = project.versions.all()[:50]
    return {
        'projectId': str(project.id),
        'versions': [version_summary(version) for version in versions],
    }


def _tool_export_summary(user, arguments: dict) -> dict:
    project = _require_project(user, arguments)
    if not can(user, project, PUBLISH):
        raise ToolError('Выгружать проект может тот, кто публикует.')
    denial = check_scenario(user, 2)
    if denial is not None:
        raise ToolError(denial.detail)

    raw_version = arguments.get('version')
    if raw_version is None:
        version = project.versions.order_by('-number').first()
        if version is None:
            raise ToolError('Сначала сохраните проект: нечего выгружать.')
    else:
        if isinstance(raw_version, bool) or not isinstance(raw_version, int):
            raise ToolError('version должен быть целым числом.')
        version = project.versions.filter(number=raw_version).first()
        if version is None:
            raise ToolError('Версия не найдена.')

    try:
        built = build_package(project, version)
    except PackageTooLarge as e:
        raise ToolError(f'Превышен технический лимит ({e}).') from e
    except ExportError as e:
        raise ToolError(str(e)) from e

    manifest = built['manifest']
    summary = {
        'projectId': str(project.id),
        'version': version.number,
        'formatVersion': manifest.get('formatVersion'),
        'blockCount': manifest.get('blocks'),
        'fileCount': len(built['files']),
        'bytes': sum(len(_bytes(content)) for content in built['files'].values()),
        'warnings': len(built['report'].warnings),
        'download': (
            f'/api/v1/projects/{project.id}/export/?version={version.number}'
        ),
    }
    if arguments.get('includeManifest'):
        summary['manifest'] = manifest
    return summary


def _bytes(content) -> bytes:
    return content if isinstance(content, bytes) else content.encode('utf-8')


TOOL_HANDLERS = {
    'list_projects': _tool_list_projects,
    'get_project': _tool_get_project,
    'list_pages': _tool_list_pages,
    'get_page': _tool_get_page,
    'list_versions': _tool_list_versions,
    'export_summary': _tool_export_summary,
}


def _call_tool(user, params: dict) -> dict:
    name = params.get('name')
    if not isinstance(name, str) or not name:
        raise RpcError(INVALID_PARAMS, 'name инструмента обязателен.')
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise RpcError(INVALID_PARAMS, f'Инструмент «{name}» не найден.')
    arguments = params.get('arguments')
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise RpcError(INVALID_PARAMS, 'arguments должен быть объектом.')

    try:
        data = handler(user, arguments)
    except ToolError as e:
        return {
            'content': [{'type': 'text', 'text': str(e)}],
            'isError': True,
        }

    text = json.dumps(data, ensure_ascii=False, indent=2)
    return {
        'content': [{'type': 'text', 'text': text}],
        'structuredContent': data,
        'isError': False,
    }


def _initialize(params: dict) -> dict:
    requested = params.get('protocolVersion')
    version = requested if requested in PROTOCOL_VERSIONS else LATEST_PROTOCOL
    return {
        'protocolVersion': version,
        'capabilities': {'tools': {'listChanged': False}},
        'serverInfo': SERVER_INFO,
        'instructions': (
            'AuraBuilder: проекты, страницы и сборка статического сайта. '
            'Инструменты только читают данные.'
        ),
    }


def handle_message(payload: Any, user) -> tuple[int, dict | None]:
    """Один JSON-RPC вызов. Возвращает (HTTP-статус, тело или None).

    None означает уведомление: по JSON-RPC на него не отвечают, и
    transport возвращает 202 без тела.
    """

    if isinstance(payload, list):
        # Пакетные запросы убраны из MCP: принимаем одиночный вызов,
        # чтобы клиент не ждал частичного выполнения пачки.
        return 400, _error(None, INVALID_REQUEST, 'Пакетные запросы не поддерживаются.')
    if not isinstance(payload, dict):
        return 400, _error(None, INVALID_REQUEST, 'Ожидается JSON-объект.')
    if payload.get('jsonrpc') != '2.0':
        return 400, _error(
            payload.get('id'), INVALID_REQUEST, 'Поле jsonrpc должно быть «2.0».',
        )
    method = payload.get('method')
    if not isinstance(method, str) or not method:
        return 400, _error(payload.get('id'), INVALID_REQUEST, 'Метод не указан.')

    if 'id' not in payload:
        # notifications/initialized и прочие уведомления не требуют ответа.
        return 202, None

    request_id = payload.get('id')
    params = payload.get('params')
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return 400, _error(request_id, INVALID_PARAMS, 'params должен быть объектом.')

    try:
        if method == 'initialize':
            result = _initialize(params)
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            result = _call_tool(user, params)
        else:
            raise RpcError(METHOD_NOT_FOUND, f'Метод «{method}» не поддерживается.')
    except RpcError as e:
        return 400, _error(request_id, e.code, e.message)
    except Exception:  # noqa: BLE001 — наружу не должен уйти стек
        logger.exception('сбой MCP-инструмента %s', method)
        return 500, _error(request_id, INTERNAL_ERROR, 'Внутренняя ошибка сервера.')

    return 200, _result(request_id, result)


__all__ = [
    'LATEST_PROTOCOL',
    'PROTOCOL_VERSIONS',
    'handle_message',
]
