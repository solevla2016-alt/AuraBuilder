"""Проверка PWA в браузере: манифест, регистрация worker, офлайн.

Проверяется то, чего не видно в тестах: браузер действительно
регистрирует service worker и отдаёт страницу из кеша при пропавшей
сети. Файл собирается из настоящей выгрузки, а не пишется руками.

    python tools/check_pwa.py
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'apps'))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def build_site(root: pathlib.Path) -> pathlib.Path:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'controlplane.settings')
    os.environ.setdefault('USE_SQLITE', '1')
    os.environ.setdefault(
        'DJANGO_SECRET_KEY', 'pwa-check-key-0123456789abcdefghijklmnop'
    )
    import django

    django.setup()

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection

    settings.DATABASES['default']['NAME'] = str(root / 'check.sqlite3')
    connection.close()
    call_command('migrate', verbosity=0, interactive=False)

    from projects.models import Project
    from projects.package import build_package
    from projects.versions import snapshot

    user = get_user_model().objects.create_user('pwa-check', password='x')
    tree = {'width': 1200, 'blocks': [{
        'id': 'b1', 'module': 'text.heading', 'x': 0, 'y': 0,
        'width': 600, 'height': 200, 'label': 'Блок',
        'props': {'text': 'Проверка PWA'},
    }]}
    project = Project.objects.create(
        owner=user, name='Цветы', tree={'width': 1200, 'blocks': []}
    )
    project.tree = tree
    project.version += 1
    project.save(update_fields=['tree', 'version'])
    version = snapshot(project, tree, author=user, label='v1')

    built = build_package(project, version, base_url='http://127.0.0.1:8080',
                          pwa=True)
    site = root / 'site'
    site.mkdir(parents=True)
    for name, content in built['files'].items():
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    return site


def main() -> int:
    root = BASE / '.pwa-check'
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    site = build_site(root)

    port = free_port()
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', port),
        functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site)),
    )
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f'http://127.0.0.1:{port}/'
    print(f'сайт с PWA поднят: {url}')
    print('manifest.json:', 'есть' if (site / 'manifest.json').exists() else 'НЕТ')
    print('service-worker.js:',
          'есть' if (site / 'service-worker.js').exists() else 'НЕТ')

    # Браузерная часть живёт в node: service worker и офлайн
    # проверяются только настоящим браузером.
    result = subprocess.run(
        [ 'node', str(BASE / 'tools' / 'probe-pwa.mjs'), url ],
        cwd=str(BASE),
    )
    server.shutdown()
    shutil.rmtree(root, ignore_errors=True)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())