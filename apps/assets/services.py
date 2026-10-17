"""Сохранение файла вместе с записью о нём.

Запись в базе и файл на диске — две вещи, и разъезжаться они должны
только в одну сторону: не может быть файла без записи, а запись без
файла означает битую картинку на сайте. Поэтому порядок здесь один:
сначала файл, потом запись, а при отказе базы файл убирается.
"""

from __future__ import annotations

from django.core.files.uploadedfile import UploadedFile

from projects.models import Project

from .models import Asset
from .storage import StoredAsset, remove, store


def save_upload(project: Project, upload: UploadedFile) -> Asset:
    """Проверяет файл, кладёт на диск и заводит запись.

    Если запись не создалась (например, упёрлась в ограничение базы),
    файл удаляется: иначе на диске копится мусор, которого не видно
    ни в медиатеке, ни при сборке пакета.
    """
    stored: StoredAsset = store(project, upload)
    try:
        return Asset.objects.create(
            project=project,
            name=stored.name,
            original_name=(upload.name or stored.name)[:255],
            content_type=stored.content_type,
            size=stored.size,
        )
    except Exception:
        remove(project, stored.name)
        raise


__all__ = ['save_upload']