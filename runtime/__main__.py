"""Запуск рантайма.

    python3 -m runtime --dir /var/lib/aurabuilder

Всё состояние — два файла в каталоге: `runtime.db` (SQLite) и
`runtime.json` (конфигурация установки с секретом). Документация для
заказчика — `docs/RUNTIME.md` в репозитории платформы и `README.md`,
который рантайм кладёт рядом с базой при первом старте.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

from .app import create_app
from .catalog import CatalogLoader
from .config import load
from .store import Store

BANNER = """Рантайм AuraBuilder.

  Адрес:        http://{host}:{port}/
  Состояние:    {dir}
  siteKey:      {site_key}

Каталог товаров подтягивается из данных пакета, если в конфигурации
задан catalogUrl. Свой каталог можно загрузить вручную:

  curl -X POST http://{host}:{port}/catalog \\
       -H 'Content-Type: application/json' \\
       -d '{{"siteKey": "{site_key}", "items": [{{"id": "t1", "name": "Роза", "price": 1200}}]}}'

За обратным прокси этот порт закрывают наружу, а рантайм оставляют
локальным: docs/RUNTIME.md, раздел «Развёртывание».
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python3 -m runtime',
        description='Рантайм опубликованного сайта AuraBuilder',
    )
    parser.add_argument('--dir', default='./runtime-data',
                        help='каталог состояния (по умолчанию ./runtime-data)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8088)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    directory = Path(args.dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    config = load(directory / 'runtime.json')
    store = Store(str(directory / 'runtime.db'))
    app = create_app(config, store)

    print(BANNER.format(
        host=args.host,
        port=args.port,
        dir=directory.resolve(),
        site_key=config.site_key,
    ))
    if not config.ready:
        print('ВНИМАНИЕ: в конфигурации нет siteKey или secret — заказы не принимаются.\n')

    # Каталог подтягивается из данных пакета на том же сервере:
    # идентификаторы товаров совпадают с кнопками «В корзину», и
    # заказчику не нужно вести список параллельно сборке сайта.
    loader = None
    if config.catalog_url:
        loader = CatalogLoader(config.catalog_url, store)
        loader.load(quiet=True)

    try:
        with make_server(args.host, args.port, app) as server:
            if loader is not None:
                threading.Thread(target=loader.run, daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        print('\nостановлен')
    finally:
        store.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
