"""Раздача опубликованного сайта.

Адрес выбран так, чтобы смена формы не меняла модель: в стенде сайт
лежит по префиксу /sites/<адрес>/, в эксплуатации это же самое будет
поддоменом или путём на CDN. Код раздачи один и тот же.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import Site
from .service import SiteNotFound, note_request, resolve

#: Расширения, которые нельзя отдавать как есть: внутри папки сайта
#: лежат манифесты и маленькие JSON-файлы, и это нормально, но исполняемый
#: код посетителю отдавать не нужно.
BLOCKED_SUFFIXES = {'.py', '.sh', '.env', '.db', '.sqlite', '.sqlite3'}


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or 'application/octet-stream'


def serve_site(request, slug: str, path: str = '') -> HttpResponse:
    """Отдаёт файл опубликованного сайта."""
    try:
        site_version, target = resolve(slug, path)
    except SiteNotFound as exc:
        # Отозванный сайт отвечает 410: посетитель должен видеть, что
        # сайт был, а 404 выглядел бы как опечатка в адресе.
        message = str(exc)
        status = 410 if 'отозван' in message else 404
        response = HttpResponse(
            '<!doctype html><meta charset="utf-8">'
            f'<title>Сайт недоступен</title><p>{message}</p>',
            status=status,
            content_type='text/html; charset=utf-8',
        )
        return response

    if target.suffix.lower() in BLOCKED_SUFFIXES:
        return HttpResponse('Файл не отдаётся', status=404)

    site = Site.objects.filter(slug=slug).first()
    if site is not None:
        note_request(site)

    # Файл читается целиком, а не отдаётся потоком: открытый поток
    # держит файл занятым, и переключить версию или убрать папку после
    # этого нельзя. Сайты ограничены лимитом экспорта.
    response = HttpResponse(target.read_bytes(), content_type=_content_type(target))
    # Сайт опубликован из версии документа: кеш безопасен только с её
    # номером, иначе после обновления посетитель держал бы старую
    # страницу до конца срока кеша.
    response['Cache-Control'] = 'public, max-age=60'
    response['X-AuraBuilder-Version'] = str(site_version.number)
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@api_view(['GET'])
@permission_classes([])
def published_site(request, slug: str):
    """Публичная страница сайта по адресу."""
    site = Site.objects.filter(slug=slug).first()
    if site is None:
        return Response({'detail': 'сайт не найден'}, status=404)
    return serve_site(request, slug, '')