"""API медиатеки проекта.

Загрузкой занимается владелец проекта, а пользоваться картинками могут
все, кто редактирует: загрузить файл от чужого имени — значит
занять место в чужом проекте.
"""

from __future__ import annotations

from io import BytesIO

from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.permissions import EDIT_CONTENT, VIEW, ProjectAccess, can
from projects.models import Project

from .models import Asset
from .services import save_upload
from .storage import AssetRejected, read, remove, url_for


def _project(project_id: str) -> Project | None:
    return Project.objects.filter(id=project_id).first()


@api_view(['GET', 'POST'])
@permission_classes([ProjectAccess])
@parser_classes([MultiPartParser, FormParser])
def assets(request, project_id: str):
    """Список файлов и загрузка нового.

    Multipart объявлен здесь: глобально платформа принимает только
    JSON, а без явного разбора загрузка файла отвечала бы 415.
    """
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        items = Asset.objects.filter(project=project)[:200]
        return Response({'assets': [a.public_dict() for a in items]})

    if request.user != project.owner:
        return Response(
            {'detail': 'Загружать файлы может владелец проекта.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    upload = request.FILES.get('file')
    if upload is None:
        return Response({'detail': 'Файл не получен.'},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        asset = save_upload(project, upload)
    except AssetRejected as e:
        return Response({'detail': str(e), 'reason': 'asset_rejected'},
                        status=status.HTTP_400_BAD_REQUEST)

    return Response(asset.public_dict(), status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([ProjectAccess])
def asset_detail(request, project_id: str, asset_id: str):
    """Удаляет файл."""
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    asset = Asset.objects.filter(id=asset_id, project=project).first()
    if asset is None:
        return Response({'detail': 'файл не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if request.user != project.owner:
        return Response(
            {'detail': 'Удалять файлы может владелец проекта.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    remove(project, asset.name)
    asset.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([ProjectAccess])
def asset_file(request, project_id: str, name: str):
    """Отдаёт файл картинки.

    Раздаёт редактор и опубликованный сайт, поэтому ответ помечен как
    кэшируемый: файл неизменяем, а имя содержит случайный хвост и
    меняется при новой загрузке того же изображения.
    """
    project = _project(project_id)
    if project is None or not can(request.user, project, EDIT_CONTENT):
        return HttpResponse(status=status.HTTP_404_NOT_FOUND)

    data = read(project, name)
    if data is None:
        return HttpResponse(status=status.HTTP_404_NOT_FOUND)
    asset = Asset.objects.filter(project=project, name=name).first()
    # BytesIO, а не сами байты: FileResponse отдаёт файл потоком и
    # ждёт от него .read() — у bytes такого метода нет.
    response = FileResponse(BytesIO(data), content_type=asset.content_type
                            if asset else 'application/octet-stream')
    # Раздаём от имени платформы, а не файлом из интернета: без этого
    # браузер откажется показывать картинку на странице другого домена.
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=86400'
    response['Content-Disposition'] = 'inline'
    if asset is not None:
        response['Content-Length'] = str(asset.size)
    return response


__all__ = ['asset_detail', 'asset_file', 'assets', 'url_for']