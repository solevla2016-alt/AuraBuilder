"""Деплой на локальный «хостинг» и проверка результата по HTTP.

Проверяется сценарий целиком: собрать пакет, разложить файлы, поднять
рантайм из выложенных файлов, запустить сайт и убедиться, что деплой
сам себя подтверждает. Никаких заглушек: сервер, который поднимает
проверка, — это тот же код, что уедет заказчику.

    python tools/check_deploy.py
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
import subprocess
import sys
import threading
import time
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
# Django-приложения живут в apps/, а их модели требуют настроек.
# Поэтому deploy импортируется внутри main(), уже после django.setup().
sys.path.insert(0, str(BASE / 'apps'))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


class Handler(http.server.SimpleHTTPRequestHandler):
    """Сайт из выложенных файлов плюс прокси на рантайм."""

    runtime_prefix = '/api/runtime'

    def log_message(self, *args) -> None:
        pass

    def _proxy(self) -> None:
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
            'REQUEST_METHOD': self.command,
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
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        self._proxy()


def main() -> int:
    sys.path.insert(0, str(BASE / 'apps'))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'controlplane.settings')
    os.environ.setdefault('USE_SQLITE', '1')
    os.environ.setdefault(
        'DJANGO_SECRET_KEY', 'deploy-check-key-0123456789abcdefghijklmnop'
    )
    import django

    django.setup()

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection

    root = BASE / '.deploy-check'
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    site = root / 'public_html'
    site.mkdir()

    settings.DATABASES['default']['NAME'] = str(root / 'check.sqlite3')
    connection.close()
    call_command('migrate', verbosity=0, interactive=False)

    from deploying.models import HostingProfile
    from deploying.service import deploy
    from projects.models import Project
    from projects.versions import snapshot

    user = get_user_model().objects.create_user('deploy-check', password='x')
    tree = {
        'width': 1200,
        'blocks': [
            {
                'id': 'b1', 'module': 'section.hero', 'x': 40, 'y': 40,
                'width': 1120, 'height': 320, 'label': 'Первый экран',
                'props': {'heading': 'Магазин «Цветы»', 'buttonLabel': 'Каталог'},
            },
            {
                'id': 'b2', 'module': 'shop.cart', 'x': 40, 'y': 400,
                'width': 540, 'height': 320, 'label': 'Корзина', 'props': {},
            },
        ],
    }
    project = Project.objects.create(
        owner=user, name='Цветы', tree={'width': 1200, 'blocks': []}
    )
    project.tree = tree
    project.version += 1
    project.save(update_fields=['tree', 'version'])
    version = snapshot(project, tree, author=user, label='v1')

    port = free_port()
    profile = HostingProfile.objects.create(
        owner=user,
        name='Локальный хостинг',
        kind='fs',
        root_path=str(site),
        site_url=f'http://127.0.0.1:{port}',
    )

    print('первый деплой: сайт ещё не поднят, проверка должна это увидеть')
    first = deploy(project, version, profile)
    print(f'  файлов: {first.files_uploaded}, ок: {first.ok}')
    for check in first.checks:
        print(f'  {"ок" if check["ok"] else "!!"} {check["name"]}: {check["detail"]}')
    if first.ok:
        print('ОШИБКА: проверка прошла, хотя сайт ещё не запущен')

    # Поднимаем сайт из выложенных файлов и запускаем рантайм из
    # выложенного кода — ровно то, что делает заказчик по README.
    runtime_dir = site / '.aurabuilder'
    config = json.loads((runtime_dir / 'runtime.json').read_text(encoding='utf-8'))
    config['catalogUrl'] = f'http://127.0.0.1:{port}/assets/data/data.json'
    config['allowedOrigins'] = [f'http://127.0.0.1:{port}']
    (runtime_dir / 'runtime.json').write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    Handler.runtime_app = None
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', port),
        functools.partial(Handler, directory=str(site)),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Рантайм импортируется из выложенной папки: проверяется тот код,
    # который действительно уедет заказчику, а не то, что лежит в
    # репозитории платформы. Отдельный процесс не поднимается — он бы
    # открыл ту же базу вторым писателем.
    sys.path.insert(0, str(runtime_dir))
    from runtime.app import create_app
    from runtime.config import load as load_runtime_config
    from runtime.store import Store

    data_dir = runtime_dir / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    # Конфигурация читается тем же кодом, что и на сервере заказчика:
    # он дополняет пустой секрет и после этого готов принимать заказы.
    # Секрет подписи cookie знает только машина заказчика: серверная
    # конфигурация приезжает с пустым секретом, и рантайм дополняет его
    # при первом запуске. Конфигурация читается выложенным кодом, а не
    # кодом из репозитория платформы.
    server_config = load_runtime_config(runtime_dir / 'runtime.json')
    store = Store(str(data_dir / 'runtime.db'))
    Handler.runtime_app = create_app(server_config, store)

    for _ in range(40):
        try:
            with urllib.request.urlopen(
                f'http://127.0.0.1:{port}/api/runtime/health', timeout=2
            ) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.25)
    else:
        print('ОШИБКА: рантайм не отвечает')
        server.shutdown()
        store.close()
        return 1

    print('повторный деплой: сайт и рантайм живы')
    second = deploy(project, version, profile)
    print(f'  файлов: {second.files_uploaded}, удалено: {second.files_removed}, '
          f'ок: {second.ok}')
    for check in second.checks:
        print(f'  {"ок" if check["ok"] else "!!"} {check["name"]}: {check["detail"]}')

    ok = first.ok is False and second.ok is True

    # Ещё одна проверка: страница после деплоя действительно отдаётся.
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=5) as response:
        html = response.read().decode('utf-8')
    print(f'  главная: {response.status}, {len(html)} байт, '
          f'есть «Цветы»: {"Цветы" in html}')

    server.shutdown()
    store.close()

    if not ok:
        print('ОШИБКА: деплой не подтвердил результат так, как ожидалось')
        return 1
    print('деплой подтверждён: файлы доехали, сайт и рантайм отвечают')
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
