"""Публикация поднимается рядом с рантаймом и проверяется по-настоящему.

Проверяется то, что ломается тихо: опубликованный сайт должен
открываться по адресу, отдавать версию в заголовке и переставать
открываться после отзыва. Всё это — через HTTP, а не вызовом
функций: раздачу обслуживает другой слой, чем публикацию.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'apps'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'controlplane.settings')
# Тестовый клиент ходит со своим именем testserver: иначе всем ответам HTTP 400
# и всё проверки сломались бы вообще не работали.
# setdefault не подходит: в .env адрес уже задан, и testserver в него
# не входит — все запросы проверки отвечали бы 400.
_allowed = os.environ.get('DJANGO_ALLOWED_HOSTS', '')
_hosts = [h.strip() for h in _allowed.split(',') if h.strip()]
_hosts += ['testserver', '127.0.0.1', 'localhost']
os.environ['DJANGO_ALLOWED_HOSTS'] = ','.join(dict.fromkeys(_hosts))
os.environ.setdefault('USE_SQLITE', '1')
os.environ.setdefault(
    'DJANGO_SECRET_KEY', 'publish-check-key-0123456789abcdefghijklmnop'
)

ROOT = pathlib.Path(tempfile.mkdtemp(prefix='aurabuilder-publish-'))
os.environ['PUBLISH_ROOT'] = str(ROOT / 'sites-root')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'controlplane.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

settings.PUBLISH_ROOT = ROOT / 'sites-root'
settings.PUBLISH_ROOT.mkdir(parents=True, exist_ok=True)

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402

settings.DATABASES['default']['NAME'] = str(ROOT / 'check.sqlite3')
connection.close()
call_command('migrate', verbosity=0, interactive=False)

from projects.models import Project  # noqa: E402
from projects.versions import snapshot  # noqa: E402

from publications.models import Site  # noqa: E402
from publications.service import backup_site, publish, withdraw  # noqa: E402


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = '') -> None:
        print(f'  {"ок" if ok else "!!"} {name}{f" ({detail})" if detail else ""}')
        if not ok:
            failures.append(name)

    user = get_user_model().objects.create_user('publish-check', password='x')
    project = Project.objects.create(
        owner=user, name='Цветы', tree={'width': 1200, 'blocks': []}
    )
    project.tree = {'width': 1200, 'blocks': [{
        'id': 'b1', 'module': 'text.heading', 'x': 0, 'y': 0,
        'width': 600, 'height': 200, 'label': 'Блок',
        'props': {'text': 'Опубликованный сайт'},
    }]}
    project.version += 1
    project.save(update_fields=['tree', 'version'])
    version = snapshot(project, project.tree, author=user, label='v1')

    # Проверка идёт через тестовый клиент Django: без этого хост
    # 'testserver' летит в разрешённых именах, а портудя убыла бь неискольким образом.
    http = Client()
    result = publish(project, version)
    site = result.site
    print(f'опубликовано: {site.url()} — {result.files} файлов, {result.size} байт')

    # --- сайт отдаётся по адресу ---------------------------------------
    response = http.get(f'/sites/{site.slug}/')
    body = response.content.decode('utf-8')
    check('главная отдаётся по адресу', response.status_code == 200,
          f'HTTP {response.status_code}')
    check('в отдаче есть содержимое проекта', 'Опубликованный сайт' in body)
    check('отдача помечена версией',
          response.headers.get('X-AuraBuilder-Version') == str(version.number),
          response.headers.get('X-AuraBuilder-Version', 'нет'))

    css = http.get(f'/sites/{site.slug}/assets/css/site.css')
    check('стили отдаются', css.status_code == 200,
          css.headers.get('Content-Type', ''))

    # --- сайт действительно открывается в браузере ----------------------
    server, address = _serve(site, ROOT)
    try:
        with urllib.request.urlopen(address + '/', timeout=5) as live:
            page = live.read().decode('utf-8')
        check('опубликованный сайт отвечает по HTTP-серверу',
              'Опубликованный сайт' in page)
    except (urllib.error.URLError, OSError) as exc:
        check('опубликованный сайт отвечает по HTTP-серверу', False, str(exc))

    # --- отзыв ----------------------------------------------------------
    withdraw(site)
    gone = http.get(f'/sites/{site.slug}/')
    check('после отзыва сайт отвечает 410, а не 404',
          gone.status_code == 410, f'HTTP {gone.status_code}')

    restored = publish(project, version)
    check('повторная публикация возвращает сайт в работу',
          restored.site.is_active and
          http.get(f'/sites/{site.slug}/').status_code == 200)

    # --- копия ----------------------------------------------------------
    backup = backup_site(restored.site)
    check('резервная копия сделана',
          backup is not None and (backup.directory / 'index.html').exists())

    # --- мониторинг -----------------------------------------------------
    for _ in range(3):
        http.get(f'/sites/{site.slug}/')
    site.refresh_from_db()
    check('обращения считаются', site.requests >= 3, str(site.requests))

    # --- границы ---------------------------------------------------------
    outside = http.get(f'/sites/{site.slug}/../../../etc/passwd')
    check('выход за пределы сайта не отдаётся',
          outside.status_code in (400, 404), f'HTTP {outside.status_code}')

    unknown = http.get('/sites/нет-такого/')
    check('неизвестный адрес отвечает 404', unknown.status_code == 404)

    server.shutdown()
    shutil.rmtree(ROOT, ignore_errors=True)

    if failures:
        print(f'\nне прошли: {", ".join(failures)}')
        return 1
    print('\nпубликация подтверждена: адрес работает, отзыв действует, копия есть')
    return 0


def _serve(site, root: pathlib.Path):
    """Поднимает обычный HTTP-сервер над теми же файлами.

    Отдельный процесс не нужен: проверяется раздача, а не воркер.
    """
    import http.server

    directory = site.current_version.directory

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f'http://{host}:{port}'


if __name__ == '__main__':
    sys.exit(main())