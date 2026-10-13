"""Пакет рантайма, который уезжает на сервер заказчика.

Задача модуля — сделать так, чтобы заказчику не пришлось ничего
догадываться: файлы сервиса, конфигурация с уже вписанным siteKey и
команда запуска, которую можно скопировать. Всё это собирается здесь
из каталога `runtime/` репозитория, а не пишется строкой в коде:
иначе на сервер уехала бы копия сервиса, которую уже нельзя было бы
исправить в том же коммите, что и сам сервис.
"""

from __future__ import annotations

import json
from pathlib import Path

from projects.package import RUNTIME_PROTOCOL_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SOURCE = REPO_ROOT / 'runtime'

# Тесты и кэши на сервер не едут: они нужны разработчику, а заказчику
# — лишние мегабайты и лишний повод что-то запустить не то.
EXCLUDED_DIRS = {'__pycache__', 'tests', '.pytest_cache'}

RUN_SCRIPT = """#!/bin/sh
# Запуск рантайма на сервере заказчика.
#
# Файл не исполняется платформой: по FTP процессы не запускаются.
# Его выполняет панель хостинга или команда в SSH-консоли.
set -eu
cd "$(dirname "$0")"
exec python3 -m runtime --dir ./data --host 127.0.0.1 --port 8088
"""

SYSTEMD_UNIT = """[Unit]
Description=AuraBuilder runtime (корзина, оформление, поиск)
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/{path}
ExecStart=/usr/bin/python3 -m runtime --dir %h/{path}/data --host 127.0.0.1 --port 8088
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

NGINX_SNIPPET = """# Правило для сайта. Порт рантайма наружу не открывается.
location /api/runtime/ {
    proxy_pass http://127.0.0.1:8088/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
}
"""

README = """# Рантайм сайта «{project}»

Здесь лежит всё, что нужно трём модулям сайта: корзина, оформление
и поиск. Остальной сайт работает как обычные статические файлы и
рантайма не требует.

## Что сделать

1. Убедиться, что сайт обслуживается с сервера и домен открывается.
2. Запустить рантайм:

   ```
   sh run.sh
   ```

   Либо как службу (systemd):

   ```
   mkdir -p ~/.config/systemd/user
   cp aura-runtime.service ~/.config/systemd/user/
   systemctl --user enable --now aura-runtime
   ```

3. Добавить правило для nginx из `nginx.conf` и перезагрузить его:

   ```
   nginx -t && nginx -s reload
   ```

4. Проверить, что всё живо:

   ```
   curl https://{domain}/api/runtime/health
   ```

   Ожидается JSON с `"ready": true`.

## Данные

Всё состояние — в папке `data`: база SQLite и конфигурация установки.
Резервная копия делается копированием папки. Пароль и ключ для cookie
лежат в `data/runtime.json` — файл нельзя отдавать в интернет.

Каталог товаров берётся из `assets/data/data.json` сайта и обновляется
раз в пять минут. Свой каталог можно загрузить вручную:

```
curl -X POST https://{domain}/api/runtime/catalog \\
     -H 'Content-Type: application/json' \\
     -d '{{"siteKey": "{site_key}", "items": []}}'
```
"""

PRIVATE_NAMES = {'__pycache__', 'tests.py', 'test_runtime.py'}


def runtime_files(project_name: str, domain: str, site_key: str, path: str) -> dict[str, str]:
    """Файлы рантайма для сервера: имя → содержимое."""
    if not RUNTIME_SOURCE.is_dir():
        raise FileNotFoundError(f'не найден каталог рантайма: {RUNTIME_SOURCE}')

    files: dict[str, str] = {}
    for source in sorted(RUNTIME_SOURCE.rglob('*.py')):
        relative = source.relative_to(RUNTIME_SOURCE)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        name = str(relative).replace('\\', '/')
        files[f'runtime/{name}'] = source.read_text(encoding='utf-8')

    files['run.sh'] = RUN_SCRIPT
    files['aura-runtime.service'] = SYSTEMD_UNIT.format(path=path.strip('/') or '.')
    files['nginx.conf'] = NGINX_SNIPPET
    files['README.md'] = README.format(
        project=project_name,
        domain=domain or 'example.ru',
        site_key=site_key,
    )
    # Конфигурация установки кладётся при первом запуске, но положить
    # её сразу — значит не заставлять заказчика ничего настраивать.
    files['runtime.json'] = json.dumps(
        {
            'version': RUNTIME_PROTOCOL_VERSION,
            'siteKey': site_key,
            'secret': '',
            'allowedOrigins': [f'https://{domain}'] if domain else [],
            'catalogUrl': f'https://{domain}/assets/data/data.json' if domain else '',
        },
        ensure_ascii=False,
        indent=2,
    ) + '\n'
    return files


__all__ = ['RUNTIME_SOURCE', 'runtime_files']
