"""Загрузка каталога из данных пакета.

Зачем: заказчик не должен вести список товаров параллельно сборке
сайта. Данные уже лежат в пакете (`assets/data/data.json`), и рантайм
берёт их оттуда же — с того же сервера, без обращения к платформе
(ТЗ п.16.4).

Обновление по расписанию, а не по каждому запросу: магазин меняет
остатки и цены минутами, а не секундами, а сайт с сотней посетителей
не должен дёргать файл сто раз в секунду.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from .store import Store, catalog_items_from_package

log = logging.getLogger('runtime')

REFRESH_SECONDS = 300
TIMEOUT = 10


class CatalogLoader:
    def __init__(self, url: str, store: Store, refresh: int = REFRESH_SECONDS) -> None:
        self.url = url
        self.store = store
        self.refresh = refresh

    def load(self, quiet: bool = False) -> int:
        """Обновляет каталог. Ошибка не поднимается: сайт должен жить
        и с устаревшим каталогом, а не падать вместе с загрузкой."""
        try:
            # Адрес из конфигурации может содержать не-ASCII символы
            # (кириллица в имени файла), а urllib принимает только
            # ASCII: без кодирования загрузка падала бы целиком.
            url = quote(self.url, safe=':/?&=%#')
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode('utf-8'))
            items = catalog_items_from_package(payload)
            if not items:
                if not quiet:
                    log.warning('в %s нет записей', self.url)
                return 0
            count = self.store.replace_catalog(items)
            if not quiet:
                log.info('каталог обновлён: %d товаров', count)
            return count
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            # Молчание здесь означало бы пустой каталог без причины.
            log.warning('каталог не обновлён (%s): %s', self.url, exc)
            return 0

    def run(self) -> None:
        while True:
            time.sleep(self.refresh)
            self.load()
