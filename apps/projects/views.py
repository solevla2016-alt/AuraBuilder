"""Представления Control Plane для вертикального среза.

Набор намеренно узкий: получить проект и сохранить дерево. Роли,
права и командная работа появятся на этапе 2 (ТЗ п.11.1).
"""

import uuid

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Project
from .serializers import ProjectCreateSerializer, ProjectSerializer


@api_view(['GET'])
def health(request):
    """Проверка живости: редактор спрашивает её перед загрузкой проекта."""
    return Response({'status': 'ok'})


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
