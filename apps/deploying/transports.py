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


def normalise_prefix(prefix: str | None) -> str:
    """Каталог сайта как абсолютный путь с завершающим слэшем.

    Пустой префикс — это корень FTP-аккаунта, и он пишется как «/»:
    иначе пути собирались бы как «assets/css/site.css» относительно
    рабочего каталога клиента, а ftplib трактует такой путь как
    относительный.
    """
    path = (prefix or '').strip().replace('\\', '/')
    if '..' in path.split('/'):
        raise DeployError(f'недопустимый каталог сайта: {prefix}')
    if not path:
        return '/'
    if not path.startswith('/'):
        path = '/' + path
    return path if path.endswith('/') else path + '/'


class FilesystemTransport:
    """Файлы раскладываются по каталогу на диске.

    `prefix` — подкаталог внутри корня. Он нужен, чтобы поведение
    совпадало с FTP: там каталог сайта указывается относительно
    домашней папки, и без него файлы раскладывались бы мимо сайта.
    """

    def __init__(self, target: str | Path, prefix: str = '') -> None:
        self.root = Path(target).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.prefix = (prefix or '').replace('\\', '/').strip('/')

    def path_for(self, name: str) -> Path:
        # resolve() с проверкой внутри root: symlink или «..» не должны
        # выпустить запись за пределы каталога сайта.
        path = (self.root / posixpath.join(self.prefix, safe_name(name))).resolve()
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
        base = (self.root / self.prefix).resolve() if self.prefix else self.root
        names: list[str] = []
        for path in base.rglob('*'):
            if path.is_file():
                names.append(str(path.relative_to(base)).replace('\\', '/'))
        return names

    def close(self) -> None:
        pass


class FtpTransport:
    """Доставка по FTP.

    Соединение переоткрывается при обрыве: деплой сайта на несколько
    сотен файлов идёт долго, и разорванное соединение посреди загрузки
    не должно начинать всё заново вручную.

    `prefix` — каталог сайта относительно домашней папки FTP
    (у Timeweb и Beget это `public_html`). Без него файлы легли бы в
    домашнюю папку, а сайт по адресу остался бы прежним, и деплой
    рапортовал бы об успехе.
    """

    def __init__(
        self,
        host: str,
        username: str,
        secret: str,
        port: int = 21,
        timeout: int = 30,
        prefix: str = '/',
    ) -> None:
        self.host = host
        self.username = username
        self.secret = secret
        self.port = port
        self.timeout = timeout
        # Префикс хранится с ведущим и завершающим слэшем: ftplib
        # считает относительный путь относительным и может положить
        # файл не туда, а путь без завершающего слэша превращается
        # в имя каталога.
        self.prefix = normalise_prefix(prefix)
        self._client: ftplib.FTP | None = None
        self._dirs: set[str] = set()

    def remote_path(self, name: str) -> str:
        """Путь на сервере: каталог сайта плюс имя файла."""
        return self.prefix + safe_name(name)

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
        if not remote_dir or remote_dir == '/' or remote_dir in self._dirs:
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
        remote = self.remote_path(name)
        directory = posixpath.dirname(remote)
        if directory and directory != '/':
            self._ensure_dir(directory)
        try:
            from io import BytesIO

            client.storbinary(f'STOR {remote}', BytesIO(content))
        except ftplib.all_errors as exc:
            raise DeployError(f'не удалось загрузить {name}: {exc}') from exc

    def remove(self, name: str) -> None:
        client = self.connect()
        try:
            client.delete(self.remote_path(name))
        except ftplib.error_perm:
            # Файла нет — удалять нечего, и это не сбой деплоя.
            pass

    def existing(self) -> list[str]:
        """Файлы каталога сайта относительно его корня.

        Обход рекурсивный: файлы лежат в assets/css, assets/js и
        assets/img, и одноуровневый список не увидел бы их. Из-за
        этого удаление устаревших файлов ничего не удаляло, а старые
        index.html и манифест оставались на сервере.

        Имена возвращаются относительно каталога сайта — такими же,
        какие приходят в put(). Иначе сравнение «что устарело» не
        находило бы ничего даже при обходе.
        """
        client = self.connect()
        base = self.prefix
        listing = self._list_dir(client, base.rstrip('/'))
        names: list[str] = []
        for item in listing:
            if item is None:
                continue
            # Имя возвращается относительно каталога сайта: такими же
            # приходят ключи пакета в put(), и только в таком виде
            # сравнение «что устарело» вообще что-то находит.
            names.append(item[len(base):] if item.startswith(base) else item)
        return sorted(names)

    def _list_dir(self, client: ftplib.FTP, remote_dir: str) -> list[str | None]:
        """Содержимое каталога. None на месте недоступного подкаталога.

        Список каталогов по цепочке, а не один: `retrlines` обрывается
        на первой же ошибке, и невидимый каталог молча терялся бы
        вместе с файлами внутри него.
        """
        try:
            names = client.nlst(remote_dir) if remote_dir else client.nlst()
        except ftplib.all_errors:
            return []
        result: list[str | None] = []
        for entry in names:
            full = posixpath.join(remote_dir, entry) if remote_dir else entry
            if self._is_dir(client, full):
                # None означает «забыть этот подкаталог»: так его
                # содержимое не попадёт под удаление устаревших файлов.
                result.append(None)
                result.extend(self._list_dir(client, full))
            else:
                result.append(full)
        return result

    def _is_dir(self, client: ftplib.FTP, path: str) -> bool:
        try:
            client.cwd(path)
        except ftplib.all_errors:
            return False
        try:
            client.cwd('/')
        except ftplib.all_errors:
            # На хостинге, где нельзя вернуться в корень, считаем
            # каталогом то, во что удалось войти: содержимое всё равно
            # обойдётся, а имя останется забытым для удаления.
            return True
        return True

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

    Каталог сайта из профиля передаётся транспорту, а не подставляется
    в имена файлов на стороне вызова: иначе префикс забыли бы в одном
    из путей, и файлы сайта легли бы рядом с ним, а сравнение
    устаревших файлов перестало бы совпадать по именам.
    """
    if profile.kind == 'fs':
        if not profile.root_path:
            raise DeployError('не указан каталог сайта')
        # Для папки на диске root_path — это и есть корень сайта, а
        # не префикс внутри него: отдельный каталог на машине заказчика
        # уже указывает на папку сайта.
        return FilesystemTransport(profile.root_path)

    if profile.kind == 'ftp':
        secret = profile.get_secret()
        if not profile.host or not profile.username or not secret:
            raise DeployError(
                'для FTP нужны хост, логин и пароль: заполните все три поля'
            )
        return FtpTransport(
            profile.host, profile.username, secret, profile.port or 21,
            prefix=profile.target_path,
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
    'normalise_prefix',
    'safe_name',
]
