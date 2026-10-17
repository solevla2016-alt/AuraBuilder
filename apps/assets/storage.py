"""Медиатека проекта: загрузка, проверка и раздача файлов.

Модули image и gallery принимают адрес картинки, но конструктором без
программиста пользуются люди, у которых картинки лежат в папке на
диске, а не по URL. Без загрузки файлов им остаётся только искать
картинку в интернете — а чужую картинку нельзя поставить на сайт
клиенту.

Проверка содержимого, а не расширения: имя «foto.png» не делает файл
картинкой, а SVG умеет исполнять скрипты от имени страницы. Поэтому
для растровых проверяется сигнатура, а из SVG вычищается всё
исполняемое.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils.text import slugify

from projects.models import Project


class AssetRejected(ValueError):
    """Файл не принят: объяснение предназначено пользователю."""


#: Растровые форматы по сигнатуре файла. Расширение не участвует:
#: переименованный .exe не становится картинкой оттого, что его так
#: назвали, а вот сигнатура врёт редко.
#:
#: Список, а не словарь: у GIF две сигнатуры (87a и 89a), и словарь
#: молча терял бы первую — файл перестал бы загружаться по типу.
RASTER = (
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
)

#: WebP проверяется по RIFF-контейнеру: «RIFF» и «WEBP» в первых
#: двенадцати байтах.
WEBP = 'image/webp'

SVG_ALLOWED = 'image/svg+xml'

#: Что ищем в SVG. Это не полноценный санитайзер, а отказ от
#: заведомо опасного содержимого: скрипты, обработчики событий,
#: внешние ссылки и опасные элементы.
SVG_FORBIDDEN = re.compile(
    rb'<\s*script|<\s*foreignobject|<\s*iframe|<\s*embed|<\s*object'
    rb'|\son\w+\s*=|javascript:|data:text/html',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StoredAsset:
    """Что получилось после проверки."""

    name: str
    content_type: str
    size: int


def asset_root() -> Path:
    """Каталог файлов проектов.

    Путь задаётся настройкой, а не вычисляется от BASE_DIR: иначе
    файлы клиентов оказались бы внутри каталога приложения, откуда
    их можно случайно закоммитить вместе с кодом.
    """
    return Path(settings.ASSET_ROOT)


def project_dir(project: Project) -> Path:
    return asset_root() / str(project.id)


def sniff(content_type: str, head: bytes) -> str | None:
    """Определяет настоящий тип по первым байтам файла."""
    for signature, mime in RASTER:
        if head.startswith(signature):
            return mime
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return WEBP
    if b'<svg' in head[:200].lower() or head.lstrip()[:5] == b'<?xml':
        return SVG_ALLOWED
    return None


def _storage_name(original: str, content_type: str) -> str:
    """Имя файла в хранилище: читаемое и не подставляемое в путь.

    Короткий хвост из случайных байт снимает коллизии: два файла
    «меню.png» из разных папок иначе перетирали бы друг друга.
    """
    stem = slugify(Path(original).stem)[:48] or 'file'
    suffix = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/svg+xml': '.svg',
    }.get(content_type, '')
    return f'{stem}-{secrets.token_hex(4)}{suffix}'


def store(project: Project, upload: UploadedFile) -> StoredAsset:
    """Проверяет и сохраняет файл проекта."""
    limit = settings.LIMITS['MAX_UPLOAD_BYTES']
    if upload.size > limit:
        raise AssetRejected(
            f'Файл больше {limit // (1024 * 1024)} МБ: уменьшите его '
            'или сожмите перед загрузкой.',
        )

    content = upload.read()
    if not content:
        raise AssetRejected('Файл пустой.')

    detected = sniff(upload.content_type or '', content[:64])
    if detected is None:
        raise AssetRejected(
            'Поддерживаются только изображения: PNG, JPEG, GIF, WebP и SVG.',
        )
    if detected == SVG_ALLOWED:
        if SVG_FORBIDDEN.search(content[:200_000]):
            raise AssetRejected(
                'В SVG найден исполняемый код. Уберите <script>, обработчики '
                'событий и внешние ссылки — и загрузите снова.',
            )

    name = _storage_name(upload.name, detected)
    directory = project_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    # Запись идёт во временный файл и переименовывается: оборванная
    # загрузка не должна оставить наполовину записанный файл, который
    # потом поставили бы на сайт.
    part = path.with_suffix(path.suffix + '.part')
    part.write_bytes(content)
    part.replace(path)

    return StoredAsset(name=name, content_type=detected, size=len(content))


def remove(project: Project, name: str) -> bool:
    """Удаляет файл. Возвращает False, если его уже нет."""
    path = project_dir(project) / name
    if not path.is_file():
        return False
    path.unlink()
    return True


def read(project: Project, name: str) -> bytes | None:
    path = project_dir(project) / name
    if not path.is_file():
        return None
    return path.read_bytes()


def url_for(project: Project, name: str) -> str:
    """Адрес файла в интерфейсе редактора."""
    return f'/api/projects/{project.id}/assets/{name}/file/'


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


__all__ = [
    'AssetRejected',
    'StoredAsset',
    'asset_root',
    'checksum',
    'project_dir',
    'read',
    'remove',
    'sniff',
    'store',
    'url_for',
]