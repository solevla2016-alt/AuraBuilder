"""Представления Control Plane для вертикального среза.

Набор намеренно узкий: получить проект и сохранить дерево. Роли,
права и командная работа появятся на этапе 2 (ТЗ п.11.1).
"""

import uuid

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Project
from .module_registry import CATEGORIES, MODULES, modules_for_stage
from .serializers import ProjectCreateSerializer, ProjectSerializer


@api_view(['GET'])
def health(request):
    """Проверка живости: редактор спрашивает её перед загрузкой проекта."""
    return Response({'status': 'ok'})


def _module_payload(module) -> dict:
    return {
        'id': module.id,
        'name': module.name,
        'category': module.category,
        'categoryLabel': module.category_label,
        'kind': module.kind,
        'stages': list(module.stages),
        'minStage': module.min_stage,
    }


@api_view(['GET'])
def module_catalog(request):
    """Каталог модулей редактора.

    Фильтр ?stage=N отдаёт модули, доступные на этапе выпуска: палитра
    в редакторе не должна показывать то, чего ещё нет в платформе.
    Без фильтра возвращается весь реестр (65 модулей).
    """
    raw_stage = request.query_params.get('stage')
    if raw_stage is None:
        modules = MODULES
    else:
        try:
            stage = int(raw_stage)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'stage должен быть целым числом'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        modules = modules_for_stage(stage)

    category_filter = request.query_params.get('category')
    if category_filter:
        modules = tuple(m for m in modules if m.category == category_filter)

    return Response(
        {
            'total': len(modules),
            'categories': [
                {'code': c['code'], 'id': c['id'], 'label': c['label']}
                for c in CATEGORIES
            ],
            'modules': [_module_payload(m) for m in modules],
        }
    )


@api_view(['GET', 'POST'])
def project_list(request):
    """Список проектов и создание нового.

    GET  — список (на стенде ограничен первыми 50 записей).
    POST — создание; при повторном UUID возвращает уже существующий
    проект, чтобы фронт мог идемпотентно инициализировать стенд.
    """
    if request.method == 'GET':
        items = Project.objects.all()[:50]
        return Response(ProjectSerializer(items, many=True).data)

    serializer = ProjectCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Повторный вызов с тем же id не должен создавать дубль: редактор
    # инициализирует стенд при каждом запуске.
    requested_id = serializer.validated_data.get('id')
    if requested_id:
        existing = Project.objects.filter(pk=requested_id).first()
        if existing:
            return Response(ProjectSerializer(existing).data, status=status.HTTP_200_OK)

    project = serializer.save()
    return Response(
        ProjectSerializer(project).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def project_detail(request, project_id: str):
    """Чтение, изменение и удаление одного проекта."""
    try:
        project = Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, AttributeError, TypeError):
        return Response({'detail': 'некорректный UUID'}, status=status.HTTP_400_BAD_REQUEST)

    if project is None:
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(ProjectSerializer(project).data)

    if request.method == 'DELETE':
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = ProjectSerializer(project, data=request.data, partial=request.method == 'PATCH')
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)
