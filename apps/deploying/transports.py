"""Транспорты доставки файлов на сервер заказчика.

Два, и оба на стандартной библиотеке:

* `FtpTransport` — настоящая доставка (ТЗ п.16.5: FTP/SFTP или API
  хостинга). У всех шести хостингов из ТЗ есть FTP, и он не меняется
  вместе с панелью управления.
* `FilesystemTransport` — каталог на диске. Он же используется в
  проверках и при локальном запуске: поднимать FTP-сервер ради теста
  значило бы тестировать не деплой, а FTP-сервер.

Оба умеют одно и то же: положить набор файлов по относительным путям
и убрать файлы, которых больше не должно быть на сервере. Второе
нужно: старый `index.html` после пересборки остался бы на месте, и
сайт показывал бы его вместо нового.
"""

from __future__ import annotations

import ftplib
import os
import posixpath
import shutil
from pathlib import Path


class DeployError(Exception):
    """Доставка не удалась. Текст идёт пользователю в интерфейс."""


def safe_name(name: str) -> str:
    """Имя файла без путей и «..».

    Имена приходят из пакета, который собирает платформа, но проверка
    всё равно нужна: у FTP есть привычка превращать путь в абсолютный,
    и одна '../' в имени увела бы файл в соседний каталог.
    """
    cleaned = name.replace('\\', '/').strip()
    if not cleaned or cleaned.startswith('/') or '..' in cleaned.split('/'):
        raise DeployError(f'недопустимое имя файла в пакете: {name}')
    return cleaned


class FilesystemTransport:
    """Файлы раскладываются по каталогу на диске."""

    def __init__(self, target: str | Path) -> None:
        self.root = Path(target).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, name: str) -> Path:
        # resolve() с проверкой внутри root: symlink или «..» не должны
        # выпустить запись за пределы каталога сайта.
        path = (self.root / safe_name(name)).resolve()
        if not str(path).startswith(str(self.root)):
            raise DeployError(f'файл выходит за пределы каталога: {name}')
        return path

    def put(self, name: str, content: bytes) -> None:
        path = self.path_for(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Сначала во временный файл: оборванная загрузка иначе оставила
        # бы на сервере половину файла, и сайт открылся бы битым.
        temp = path.with_name(path.name + '.part')
        temp.write_bytes(content)
        temp.replace(path)

    def remove(self, name: str) -> None:
        path = self.path_for(name)
        if path.is_file():
            path.unlink()

    def existing(self) -> list[str]:
        names: list[str] = []
        for path in self.root.rglob('*'):
            if path.is_file():
                names.append(str(path.relative_to(self.root)).replace('\\', '/'))
        return names

    def close(self) -> None:
        pass


class FtpTransport:
    """Доставка по FTP.

    Соединение переоткрывается при обрыве: деплой сайта на несколько
    сотен файлов идёт долго, и разорванное соединение посреди загрузки
    не должно начинать всё заново вручную.
    """

    def __init__(
        self,
        host: str,
        username: str,
        secret: str,
        port: int = 21,
        timeout: int = 30,
    ) -> None:
        self.host = host
        self.username = username
        self.secret = secret
        self.port = port
        self.timeout = timeout
        self._client: ftplib.FTP | None = None
        self._dirs: set[str] = set()

    def connect(self) -> ftplib.FTP:
        if self._client is not None:
            return self._client
        try:
            client = ftplib.FTP(timeout=self.timeout)
            client.connect(self.host, self.port)
            client.login(self.username, self.secret)
            client.set_pasv(True)
            self._client = client
            return client
        except ftplib.all_errors as exc:
            raise DeployError(f'не удалось подключиться к {self.host}: {exc}') from exc

    def _ensure_dir(self, remote_dir: str) -> None:
        if not remote_dir or remote_dir in self._dirs or remote_dir == '/':
            return
        client = self.connect()
        parent = posixpath.dirname(remote_dir.rstrip('/'))
        if parent and parent != '/':
            self._ensure_dir(parent)
        try:
            client.mkd(remote_dir)
        except ftplib.error_perm as exc:
            # Каталог уже есть — это не ошибка: при повторном деплое
            # он создавался в прошлый раз.
            if not str(exc).startswith('550'):
                raise DeployError(f'не удалось создать каталог {remote_dir}: {exc}') from exc
        self._dirs.add(remote_dir)

    def put(self, name: str, content: bytes) -> None:
        client = self.connect()
        remote = safe_name(name)
        directory = posixpath.dirname(remote)
        if directory:
            self._ensure_dir('/' + directory.lstrip('/'))
        try:
            from io import BytesIO

            client.storbinary(f'STOR {remote}', BytesIO(content))
        except ftplib.all_errors as exc:
            raise DeployError(f'не удалось загрузить {name}: {exc}') from exc

    def remove(self, name: str) -> None:
        client = self.connect()
        try:
            client.delete(safe_name(name))
        except ftplib.error_perm:
            # Файла нет — удалять нечего, и это не сбой деплоя.
            pass

    def existing(self) -> list[str]:
        client = self.connect()
        found: list[str] = []

        def walk(remote_dir: str) -> None:
            try:
                entries = client.mlsd(remote_dir) if hasattr(client, 'mlsd') else []
            except ftplib.all_errors:
                return
            for entry in entries:
                if entry.get('type') not in (None, 'file'):
                    continue
                full = posixpath.join(remote_dir, entry['name'])
                found.append(full.lstrip('/'))
                if entry.get('type') == 'dir':
                    walk(full)

        walk('')
        return found

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.quit()
            except ftplib.all_errors:
                # Закрытие не важно: соединение и так оборвётся по таймауту.
                pass
            self._client = None


def build_transport(profile) -> FilesystemTransport | FtpTransport:
    """Транспорт по профилю.

    Недостающие данные проверяются здесь, а не по месту: «нет пароля»
    должно говориться до первой загрузки, иначе пользователь увидит
    обрыв где-то в середине.
    """
    if profile.kind == 'fs':
        if not profile.root_path:
            raise DeployError('не указан каталог сайта')
        return FilesystemTransport(profile.root_path)

    if profile.kind == 'ftp':
        secret = profile.get_secret()
        if not profile.host or not profile.username or not secret:
            raise DeployError(
                'для FTP нужны хост, логин и пароль: заполните все три поля'
            )
        return FtpTransport(
            profile.host, profile.username, secret, profile.port or 21
        )

    raise DeployError(f'неизвестный способ доступа: {profile.kind}')


def copy_tree(source: str | Path, transport, prefix: str = '') -> list[str]:
    """Кладёт дерево каталога в транспорт под префиксом.

    Возвращает список загруженных имён: по нему потом считается, что
    удалить с сервера.
    """
    root = Path(source)
    uploaded: list[str] = []
    for path in sorted(root.rglob('*')):
        if path.is_dir() or '__pycache__' in path.parts:
            continue
        name = posixpath.join(prefix, str(path.relative_to(root)).replace('\\', '/'))
        transport.put(name, path.read_bytes())
        uploaded.append(name)
    return uploaded


def clear_directory(path: str | Path) -> None:
    """Очищает каталог, не удаляя его самого.

    Нужна при локальной сборке пакета рантайма: старые файлы прошлой
    версии иначе останутся, и сервер будет запускать не тот код.
    """
    target = Path(path)
    if not target.exists():
        return
    for item in target.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


__all__ = [
    'DeployError',
    'FilesystemTransport',
    'FtpTransport',
    'build_transport',
    'clear_directory',
    'copy_tree',
]
