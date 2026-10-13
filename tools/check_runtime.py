"""Поднимает собранный пакет вместе с рантаймом и ждёт браузерную проверку.

Зачем отдельный скрипт: модули корзины, оформления и поиска работают
только в паре «файлы пакета + живой рантайм + браузер». Тесты рантайма
проверяют сервер, тесты выгрузки — разметку, но никто не проверяет,
что клиент из пакета действительно оживляет блоки.

    python tools/check_runtime.py
    node tools/probe.mjs http://127.0.0.1:PORT/ --wait '.rt-cart' --eval ...

Печатает адрес и держит сервер, пока скрипт работает; Ctrl+C останавливает.
"""

from __future__ import annotations

import functools
import http.server
import io
import json
import os
import pathlib
import shutil
import socket
import sys
import threading
import zipfile

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from runtime.app import create_app  # noqa: E402
from runtime.catalog import CatalogLoader  # noqa: E402
from runtime.config import Config  # noqa: E402
from runtime.store import Store  # noqa: E402

SITE_KEY = 'check-site-key'
SECRET = 'check-secret'


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


class Handler(http.server.SimpleHTTPRequestHandler):
    """Отдаёт статику пакета; /runtime уходит в рантайм.

    Один порт вместо двух: в жизни это делает обратный прокси, и
    проверка должна идти через него, а не в обход.
    """

    # Префикс /api/runtime, а не /runtime: файл runtime.json лежит в
    # корне сайта, и прокси на /runtime перехватывал бы его, и сайт
    # перестал бы открываться (docs/RUNTIME.md).
    runtime_prefix = '/api/runtime'

    def log_message(self, *args) -> None:  # прогон должен быть тихим
        pass

    def _proxy(self, method: str) -> None:
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else b''
        path = self.path[len(self.runtime_prefix):] or '/'
        query = ''
        if '?' in path:
            path, query = path.split('?', 1)
        captured: dict = {}

        def start_response(status, headers):
            captured['status'] = status
            captured['headers'] = headers

        chunks = self.runtime_app({
            'REQUEST_METHOD': method,
            'PATH_INFO': path,
            'QUERY_STRING': query,
            'CONTENT_TYPE': self.headers.get('Content-Type', ''),
            'CONTENT_LENGTH': str(length),
            'HTTP_X_SITE_KEY': self.headers.get('X-Site-Key', ''),
            'HTTP_ORIGIN': self.headers.get('Origin', ''),
            'HTTP_COOKIE': self.headers.get('Cookie', ''),
            'REMOTE_ADDR': '127.0.0.1',
            'wsgi.input': io.BytesIO(body),
            'wsgi.url_scheme': 'http',
        }, start_response)

        self.send_response(int(captured['status'].split()[0]))
        for name, value in captured['headers']:
            if name.lower() == 'set-cookie':
                self.send_header('Set-Cookie', value)
            else:
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(b''.join(chunks))

    def do_GET(self) -> None:
        if self.path.startswith(self.runtime_prefix):
            self._proxy('GET')
        else:
            super().do_GET()

    def do_POST(self) -> None:
        self._proxy('POST')


def page_tree(source_id: str) -> dict:
    """Страница из четырёх коммерческих модулей этапа 6."""
    return {
        'width': 1200,
        'blocks': [
            {
                'id': 'b1', 'module': 'shop.catalog', 'x': 40, 'y': 40,
                'width': 620, 'height': 320, 'label': 'Каталог',
                'props': {'source': source_id, 'titleField': 'name',
                          'priceField': 'cost', 'limit': 6, 'columns': 3},
            },
            {
                'id': 'b2', 'module': 'shop.cart', 'x': 700, 'y': 40,
                'width': 340, 'height': 320, 'label': 'Корзина', 'props': {},
            },
            {
                'id': 'b3', 'module': 'shop.checkout', 'x': 700, 'y': 400,
                'width': 340, 'height': 320, 'label': 'Оформление', 'props': {},
            },
            {
                'id': 'b4', 'module': 'shop.search', 'x': 40, 'y': 400,
                'width': 620, 'height': 320, 'label': 'Поиск', 'props': {},
            },
        ],
    }


def build_site(root: pathlib.Path) -> pathlib.Path:
    """Собирает пакет проекта и распаковывает его на диск."""
    sys.path.insert(0, str(BASE / 'apps'))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'controlplane.settings')
    os.environ.setdefault('USE_SQLITE', '1')
    os.environ.setdefault(
        'DJANGO_SECRET_KEY',
        'test-key-0123456789abcdefghijklmnopqrstuvwxyz-0123456789',
    )
    import django

    django.setup()

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection

    # Своя база: проверка не должна видеть и портить рабочие проекты
    # разработчика. Таблицы появляются до первого обращения к ним.
    settings.DATABASES['default']['NAME'] = str(root / 'check.sqlite3')
    connection.close()
    call_command('migrate', verbosity=0, interactive=False)

    from data_sources.models import DataRecord, DataSource
    from projects.models import Project
    from projects.package import build_package, package_zip
    from projects.versions import snapshot

    user = get_user_model().objects.create_user('runtime-check', password='x')
    project = Project.objects.create(
        owner=user, name='Проверка рантайма', tree={'width': 1200, 'blocks': []}
    )
    source = DataSource.objects.create(
        project=project, name='Каталог', key='katalog',
        fields=[{'key': 'name', 'label': 'Название', 'type': 'text', 'required': True},
                {'key': 'cost', 'label': 'Цена', 'type': 'number', 'required': False}],
    )
    for name, cost in (('Роза', 1200), ('Тюльпан', 900), ('Лилия', 1500)):
        DataRecord.objects.create(source=source, data={'name': name, 'cost': cost})

    tree = page_tree(str(source.id))
    project.tree = tree
    project.save(update_fields=['tree'])
    version = snapshot(project, tree, author=user, label='проверка')

    built = build_package(project, version, base_url='http://127.0.0.1:8000')
    _, blob = package_zip(built['files'])
    site = root / 'site'
    site.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(site)

    # runtime.json заполняется так, как это делает заказчик или
    # One-Click Deploy: адрес своего сервера и выданный siteKey.
    config = json.loads((site / 'runtime.json').read_text(encoding='utf-8'))
    config['siteKey'] = SITE_KEY
    (site / 'runtime.json').write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'пакет собран: {len(built["files"])} файлов')
    return site


def main() -> int:
    root = BASE / '.runtime-check'
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    site = build_site(root)
    store = Store(str(root / 'runtime.db'))
    port = free_port()

    # Сайт поднимается первым: рантайм забирает каталог из его данных
    # по адресу — ровно так же, как это будет на сервере заказчика.
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', port),
        functools.partial(Handler, directory=str(site)),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    payload = json.loads((site / 'runtime.json').read_text(encoding='utf-8'))
    payload['endpoint'] = f'http://127.0.0.1:{port}/api/runtime'
    (site / 'runtime.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    config = Config({
        'version': 1, 'siteKey': SITE_KEY, 'secret': SECRET,
        'allowedOrigins': [],
        'catalogUrl': f'http://127.0.0.1:{port}/assets/data/data.json',
    })
    Handler.runtime_app = create_app(config, store)
    # Каталог не задаётся вручную: он берётся из данных пакета, и
    # идентификаторы t1, t2… совпадают с кнопками «В корзину».
    loaded = CatalogLoader(config.catalog_url, store).load(quiet=True)
    print(f'каталог из данных пакета: {loaded} товаров')

    print(f'сайт и рантайм подняты: http://127.0.0.1:{port}/')
    print('Ctrl+C — остановить')
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print('\nостановлено')
    finally:
        server.shutdown()
        store.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
