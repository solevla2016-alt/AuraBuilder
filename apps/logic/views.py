"""API логики: библиотека нод, чтение и проверка графа.

Редактору нужны три вещи: список типов нод для левой панели, текущий
граф и проверка перед сохранением. Отдельного «компилировать» на
сервере нет — файл появляется в пакете, а предпросмотр собирает его
тем же кодом, что и сборка: два пути разошлись бы однажды.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import EDIT_CONTENT, IsAuthenticatedUser, can
from projects.models import Project

from .compiler import compile_graph
from .graph import LogicError, extract, is_empty, validate
from .nodes import library


def _project(project_id: str) -> Project | None:
    return Project.objects.filter(id=project_id).first()


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def logic_library(request):
    """Библиотека типов нод (ТЗ: библиотека нод слева)."""
    return Response({'types': library()})


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def logic_graph_view(request, project_id: str):
    """Граф логики проекта и результат его проверки.

    Ответ всегда включает проверку: интерфейс показывает проблемы
    прямо в редакторе, а не после неудачной сборки.
    """
    project = _project(project_id)
    if project is None or not can(request.user, project, 'view'):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    tree = project.tree if isinstance(project.tree, dict) else {}
    raw = extract(tree)
    payload: dict = {
        'projectId': str(project.id),
        'graph': raw if isinstance(raw, dict) else {'nodes': [], 'edges': []},
        'empty': is_empty(raw),
        'types': library(),
    }
    try:
        graph = validate(raw)
    except LogicError as e:
        payload['valid'] = False
        payload['problems'] = str(e).split('; ')
        return Response(payload)

    payload['valid'] = True
    payload['problems'] = []
    payload['stats'] = {
        'nodes': len(graph.nodes),
        'edges': len(graph.edges),
        'triggers': len(graph.triggers()),
    }
    return Response(payload)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def logic_check(request, project_id: str):
    """Проверяет присланный граф и показывает скомпилированный скрипт.

    Предпросмотр: то, что человек увидит в редакторе, должно быть
    тем же файлом, который попадёт в пакет.
    """
    project = _project(project_id)
    if project is None or not can(request.user, project, 'view'):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    raw = (request.data or {}).get('graph')
    try:
        compiled = compile_graph(raw)
    except LogicError as e:
        return Response({'valid': False, 'problems': str(e).split('; ')},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    if not can(request.user, project, EDIT_CONTENT):
        return Response(
            {'detail': 'Правку логики может тот, кто редактирует проект.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response({
        'valid': True,
        'problems': [],
        'stats': {
            'nodes': compiled['nodes'],
            'actions': compiled['actions'],
            'requiresRuntime': compiled['hasRuntimeNodes'],
        },
        'script': compiled['script'],
    })


__all__ = ['logic_check', 'logic_graph_view', 'logic_library']