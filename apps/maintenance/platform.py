"""Резервная копия платформы: база и пользовательские файлы.

Почему в одном архиве, а не только дамп базы: опубликованные сайты и
картинки медиатеки лежат на томах. Восстановленная база без них дала бы
проект, который ссылается на несуществующие файлы, — то есть копию,
которая формально есть, а пользоваться ей нельзя.

Почему manifest.json с контрольными суммами: архив переносят между
машинами и хранят месяцами. Без проверки испорченный gzip или неполная
копия восстанавливались бы молча, и обнаружилось бы это уже на рабочем
стенде. Суммы считаются по содержимому файлов, а не по байтам tar.gz:
mtime и права меняются от обычного копирования, содержимое — нет.

Ключи шифрования секретов в архив не попадают по умолчанию. Это
осознанно: без ключей восстановленные секреты нечитаемы, но и ключи в
архиве с базой — это пароль, приклеенный к замку. Флаг
--include-secret-keys добавляет их отдельным файлом и предупреждает
оператора.

Команды рассчитаны на остановленный сервис. SQLite-снимок снимается
через backup API и на работающей базе, но восстановление заменяет
файлы, которые gunicorn в это время раздаёт.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connections

#: Метка формата. Читается до восстановления: архив чужой программы не
#: должен попасть в restore_platform по ошибке оператора.
FORMAT = 'aurabuilder-platform-backup'
FORMAT_VERSION = 1

MANIFEST_NAME = 'manifest.json'
KEYS_NAME = 'keys.env'

#: Каталоги, которые входят в копию. Имя нужно для manifest: путь на
#: новом хосте может быть другим, а содержимое — тем же.
DIRECTORIES = (
    ('published', 'PUBLISH_ROOT'),
    ('assets', 'ASSET_ROOT'),
    ('media', 'MEDIA_ROOT'),
)


@dataclass(frozen=True)
class DirectoryBackup:
    """Описание каталога в архиве."""

    name: str
    path: str
    sha256: str
    files: int
    bytes: int


def current_directories() -> list[tuple[str, Path]]:
    """Каталоги платформы, которые нужно сохранить.

    MEDIA_ROOT по умолчанию пуст: платформа хранит картинки в
    ASSET_ROOT. Если заказчик задал MEDIA_ROOT (например, для админки),
    он попадёт в копию автоматически.
    """
    directories: list[tuple[str, Path]] = []
    for name, setting in DIRECTORIES:
        raw = getattr(settings, setting, '') or ''
        if not raw:
            continue
        directories.append((name, Path(raw)))
    return directories


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(root: Path) -> tuple[str, int, int]:
    """Слепок содержимого каталога: sha256, файлов, байт.

    Символические ссылки пропускаются: tar с filter='data' отказывается
    восстанавливать ссылки за пределы каталога, и копия, которая не
    восстановится, хуже копии без ссылки. Содержимое таких файлов
    платформа не раздаёт.
    """
    digest = hashlib.sha256()
    files = 0
    total = 0
    if not root.exists():
        return digest.hexdigest(), 0, 0
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode('utf-8'))
        digest.update(b'\0')
        digest.update(file_sha256(path).encode('ascii'))
        digest.update(b'\n')
        files += 1
        total += path.stat().st_size
    return digest.hexdigest(), files, total


def directory_backups(directories: list[tuple[str, Path]]) -> list[DirectoryBackup]:
    result = []
    for name, root in directories:
        digest, files, size = hash_tree(root)
        result.append(
            DirectoryBackup(
                name=name,
                path=f'files/{name}',
                sha256=digest,
                files=files,
                bytes=size,
            )
        )
    return result


def snapshot_sqlite(connection, destination: Path) -> None:
    """Согласованный снимок SQLite через backup API.

    Копировать файл нельзя: при включённом WAL последние записи лежат в
    -wal, и обычная копия открылась бы без них. backup API снимает
    целое состояние базы, пока приложение продолжает работать.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection.ensure_connection()
    target = sqlite3.connect(str(destination))
    try:
        connection.connection.backup(target)
    finally:
        target.close()


def restore_sqlite(source: Path, destination: Path) -> None:
    """Заменить базу содержимым снимка.

    Используется backup API, а не копирование поверх файла: Windows и
    открытые дескрипторы не дают перезаписать файл, который кто-то
    держит, а backup API работает через соединение SQLite.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(str(source))
    target_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _postgres_params() -> dict[str, str]:
    # settings_dict, а не settings.DATABASES: тестовый раннер
    # подменяет имя на test_<база>, и pg_dump должен снимать именно ту
    # базу, с которой работает Django, а не пустую рабочую.
    database = connections['default'].settings_dict
    return {
        'host': str(database.get('HOST') or ''),
        'port': str(database.get('PORT') or ''),
        'user': str(database.get('USER') or ''),
        'name': str(database.get('NAME') or ''),
        'password': str(database.get('PASSWORD') or ''),
    }


def _run_pg(command: list[str], action: str) -> None:
    params = _postgres_params()
    environment = os.environ.copy()
    if params['password']:
        environment['PGPASSWORD'] = params['password']
    args = [command[0]]
    if params['host']:
        args += ['--host', params['host']]
    if params['port']:
        args += ['--port', params['port']]
    if params['user']:
        args += ['--username', params['user']]
    args += command[1:]
    try:
        subprocess.run(
            args,
            check=True,
            env=environment,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise CommandError(
            f'{command[0]} не найден. Установите postgresql-client той же '
            'или более новой мажорной версии, что и сервер PostgreSQL. '
            'В образе docker/Dockerfile.api он уже есть.'
        ) from None
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or '').strip() or str(error)
        raise CommandError(f'{action}: {detail}') from None


def snapshot_database(destination: Path) -> dict:
    """Снимок базы в каталог сборки архива."""
    vendor = connections['default'].vendor
    if vendor == 'sqlite':
        name = 'database.sqlite3'
        path = destination / name
        snapshot_sqlite(connections['default'], path)
    elif vendor == 'postgresql':
        name = 'database.dump'
        path = destination / name
        _run_pg(
            ['pg_dump', '--format=custom', '--no-owner', '--no-privileges',
             '--file', str(path), _postgres_params()['name']],
            'pg_dump',
        )
    else:
        raise CommandError(f'резервное копирование не поддерживает БД «{vendor}»')
    return {
        'vendor': vendor,
        'file': name,
        'sha256': file_sha256(path),
        'size': path.stat().st_size,
    }


def check_database_vendor(vendor: str) -> None:
    """Совпадает ли СУБД архива с текущей.

    Дамп PostgreSQL нельзя загрузить в SQLite и наоборот, а сообщение
    «pg_restore: ошибка» оператору ничего не объясняет.
    """
    current = connections['default'].vendor
    if vendor != current:
        raise CommandError(
            f'архив снят с базы «{vendor}», а текущая база — «{current}». '
            'Восстановление между разными СУБД не поддерживается: '
            'перенесите установку на ту же СУБД или снимите копию заново.'
        )


def database_file(staging: Path, manifest: dict) -> Path:
    """Файл базы из manifest; путь проверен на выход за пределы архива."""
    database = manifest.get('database') or {}
    return _inside(staging, database.get('file'))


def restore_database(source: Path, vendor: str) -> None:
    """Заменить текущую базу содержимым архива.

    Соединения закрываются до восстановления: открытое соединение
    Django держит старую схему в кеше и после подмены продолжило бы
    писать в неё.
    """
    check_database_vendor(vendor)
    database_name = str(connections['default'].settings_dict['NAME'])
    connections.close_all()
    if vendor == 'sqlite':
        if database_name == ':memory:':
            raise CommandError('нельзя восстановить базу в память: укажите файл SQLite')
        restore_sqlite(source, Path(database_name))
    elif vendor == 'postgresql':
        _run_pg(
            ['pg_restore', '--clean', '--if-exists', '--no-owner',
             '--no-privileges', '--single-transaction', '--exit-on-error',
             '--dbname', _postgres_params()['name'], str(source)],
            'pg_restore',
        )


def _add_tree(archive: tarfile.TarFile, root: Path, arcname: str) -> None:
    if not root.exists():
        return
    archive.add(root, arcname=arcname, recursive=False)
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        archive.add(path, arcname=f'{arcname}/{relative}', recursive=False)


def create_backup(
    destination: Path,
    *,
    include_secret_keys: bool = False,
    directories: list[tuple[str, Path]] | None = None,
    log=None,
) -> dict:
    """Собрать архив и вернуть его manifest.

    Сначала снимок собирается во временном каталоге, и только потом
    пишется tar.gz: недописанный архив не должен лежать рядом с
    рабочими копиями под видом готового.
    """
    directories = current_directories() if directories is None else directories
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    keys = (getattr(settings, 'DJANGO_SECRET_ENCRYPTION_KEYS', '') or '').strip()
    if include_secret_keys and not keys:
        raise CommandError(
            'в окружении не задан DJANGO_SECRET_ENCRYPTION_KEYS — '
            'добавлять в архив нечего'
        )

    with tempfile.TemporaryDirectory(prefix='aurabuilder-backup-') as raw:
        staging = Path(raw)
        database = snapshot_database(staging)
        entries = directory_backups(directories)

        if include_secret_keys:
            keys_file = staging / KEYS_NAME
            keys_file.write_text(
                f'DJANGO_SECRET_ENCRYPTION_KEYS={keys}\n',
                encoding='utf-8',
            )
            # Ключи лежат в архиве, но не должны быть читаемы соседним
            # процессам на машине, где копия собирается.
            keys_file.chmod(0o600)

        manifest = {
            'format': FORMAT,
            'format_version': FORMAT_VERSION,
            'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'deployment_mode': settings.DEPLOYMENT_MODE,
            'database': database,
            'directories': [
                {
                    'name': entry.name,
                    'path': entry.path,
                    'sha256': entry.sha256,
                    'files': entry.files,
                    'bytes': entry.bytes,
                }
                for entry in entries
            ],
            'keys': {
                'included': include_secret_keys,
                'file': KEYS_NAME if include_secret_keys else None,
            },
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )

        if log is not None:
            log(
                f'база: {database["vendor"]}, '
                f'каталогов: {len(entries)}, '
                f'файлов: {sum(entry.files for entry in entries)}, '
                f'байт: {sum(entry.bytes for entry in entries)}'
            )

        with tarfile.open(destination, 'w:gz') as archive:
            archive.add(staging / MANIFEST_NAME, arcname=MANIFEST_NAME)
            archive.add(staging / database['file'], arcname=database['file'])
            if include_secret_keys:
                archive.add(staging / KEYS_NAME, arcname=KEYS_NAME)
            for entry in entries:
                root = next(
                    (path for name, path in directories if name == entry.name),
                    None,
                )
                if root is not None:
                    _add_tree(archive, root, entry.path)
    return manifest


def _read_manifest(staging: Path) -> dict:
    manifest_path = staging / MANIFEST_NAME
    if not manifest_path.is_file():
        raise CommandError('в архиве нет manifest.json: это не копия AuraBuilder')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise CommandError(f'manifest.json повреждён: {error}') from None
    if not isinstance(manifest, dict):
        raise CommandError('manifest.json должен быть объектом')
    if manifest.get('format') != FORMAT:
        raise CommandError(f'неизвестный формат архива: {manifest.get("format")!r}')
    if manifest.get('format_version') != FORMAT_VERSION:
        raise CommandError(
            f'версия формата {manifest.get("format_version")!r} не поддерживается, '
            f'ожидается {FORMAT_VERSION}'
        )
    database = manifest.get('database')
    if not isinstance(database, dict) or not database.get('file'):
        raise CommandError('в manifest.json нет описания базы')
    directories = manifest.get('directories')
    if not isinstance(directories, list):
        raise CommandError('в manifest.json нет списка каталогов')
    for entry in directories:
        if not isinstance(entry, dict) or not entry.get('name') or not entry.get('path'):
            raise CommandError('в manifest.json некорректное описание каталога')
    return manifest


def _inside(staging: Path, relative: object) -> Path:
    """Путь из manifest, гарантированно лежащий внутри распакованного архива.

    manifest — обычный JSON из внешнего файла. Без проверки строка
    `../../etc/passwd` заставила бы восстановление читать файлы хоста
    и сравнивать их с хешем, который злоумышленник тоже положил в архив.
    """
    if not isinstance(relative, str) or not relative:
        raise CommandError('в manifest.json пустой путь')
    path = (staging / relative).resolve()
    root = staging.resolve()
    if path != root and root not in path.parents:
        raise CommandError(f'manifest.json ссылается за пределы архива: {relative}')
    return path


def _verify_archive(staging: Path, manifest: dict) -> None:
    database = manifest.get('database') or {}
    database_file = _inside(staging, database.get('file'))
    if not database_file.is_file():
        raise CommandError('в архиве нет файла базы, указанного в manifest.json')
    if file_sha256(database_file) != database.get('sha256'):
        raise CommandError('контрольная сумма базы не совпала: архив повреждён')

    for entry in manifest.get('directories') or []:
        root = _inside(staging, entry.get('path'))
        digest, files, _ = hash_tree(root)
        if digest != entry.get('sha256') or files != entry.get('files'):
            raise CommandError(
                f'контрольная сумма каталога «{entry.get("name")}» не совпала: '
                'архив повреждён или изменён'
            )


@contextmanager
def opened_archive(archive: Path) -> Iterator[tuple[Path, dict]]:
    """Распаковать архив во временный каталог и проверить целиком.

    Проверка идёт до восстановления: если хеши не совпали, рабочие
    каталоги и база остаются нетронутыми.
    """
    staging = Path(tempfile.mkdtemp(prefix='aurabuilder-restore-'))
    try:
        try:
            with tarfile.open(Path(archive), 'r:gz') as source:
                # filter='data' запрещает абсолютные пути и ссылки за
                # пределы каталога. Архив может прийти извне, и доверять
                # именам внутри нельзя.
                source.extractall(staging, filter='data')
        except (tarfile.TarError, OSError) as error:
            raise CommandError(f'не удалось прочитать архив: {error}') from None
        manifest = _read_manifest(staging)
        _verify_archive(staging, manifest)
        yield staging, manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def restore_files(
    staging: Path,
    manifest: dict,
    directories: list[tuple[str, Path]] | None = None,
    *,
    log=None,
) -> list[Path]:
    """Вернуть каталоги платформы из архива.

    Старое содержимое не удаляется: оно переезжает в соседний каталог
    `<имя>.before-restore-<время>`. Переименовать сам каталог нельзя —
    в Docker это точка монтирования тома, — поэтому переносится
    содержимое.
    """
    directories = current_directories() if directories is None else directories
    known = dict(directories)
    saved: list[Path] = []

    for entry in manifest.get('directories') or []:
        name = str(entry.get('name') or '')
        target = known.get(name)
        if target is None:
            raise CommandError(
                f'в архиве есть каталог «{name}», но в этом окружении он не '
                'задан. Укажите путь в переменной окружения (PUBLISH_ROOT, '
                'ASSET_ROOT или MEDIA_ROOT) и повторите восстановление.'
            )
        source = _inside(staging, entry.get('path'))
        target.mkdir(parents=True, exist_ok=True)

        old_path: Path | None = None
        if any(target.iterdir()):
            old_path = target.with_name(f'{target.name}.before-restore-{_timestamp()}')
            suffix = 1
            while old_path.exists():
                old_path = target.with_name(
                    f'{target.name}.before-restore-{_timestamp()}-{suffix}'
                )
                suffix += 1
            old_path.mkdir(parents=True)
            for child in target.iterdir():
                shutil.move(str(child), str(old_path / child.name))
            saved.append(old_path)
            if log is not None:
                log(f'старое содержимое «{name}»: {old_path}')

        if not source.is_dir():
            # Пустой каталог на момент копии: восстанавливать нечего,
            # но и падать незачем — manifest уже подтвердил, что так и
            # было задумано.
            continue
        shutil.copytree(source, target, dirs_exist_ok=True)

    return saved


def keys_path_after_restore(staging: Path, manifest: dict) -> Path | None:
    """Ключи из архива кладутся рядом, но не применяются сами.

    Подставлять их в окружение работающего процесса бессмысленно: их
    читают только при старте. Оператор должен увидеть путь и перенести
    значения в конфигурацию — молчаливая подмена ключей выглядела бы
    как «секреты восстановились», хотя процесс продолжил бы работать
    со старым кольцом.
    """
    keys = manifest.get('keys') or {}
    if not keys.get('included'):
        return None
    source = _inside(staging, keys.get('file'))
    if not source.is_file():
        raise CommandError('manifest обещает ключи, но файла ключей в архиве нет')
    destination = Path.cwd() / 'restore-keys.env'
    shutil.copyfile(source, destination)
    destination.chmod(0o600)
    return destination


__all__ = [
    'FORMAT',
    'FORMAT_VERSION',
    'check_database_vendor',
    'create_backup',
    'current_directories',
    'database_file',
    'file_sha256',
    'hash_tree',
    'keys_path_after_restore',
    'opened_archive',
    'restore_database',
    'restore_files',
    'restore_sqlite',
    'snapshot_database',
    'snapshot_sqlite',
]
