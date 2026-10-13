"""Хранилище рантайма: каталог, корзины и заказы в одном файле SQLite.

Почему SQLite: магазин, у которого товаров меньше, чем заказов в неделю,
не должен получать отдельный сервер базы данных только из-за корзины.
Отдельный Postgres — это условие приёмки, которого у заказчика нет и
которое не нужно (ADR-0005).

Схема создаётся при первом старте и версионируется через
`PRAGMA user_version`: обновление рантайма не требует ручных действий,
но и не молча теряет данные — версия записывается рядом с ними.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from typing import Any

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    price       REAL NOT NULL DEFAULT 0,
    search      TEXT NOT NULL DEFAULT '',
    name_key    TEXT NOT NULL DEFAULT '',
    search_key  TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS carts (
    sid         TEXT PRIMARY KEY,
    payload     TEXT NOT NULL DEFAULT '{"items": []}',
    updated_at  REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id          TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    total       REAL NOT NULL DEFAULT 0,
    items       INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  REAL NOT NULL
);
"""

# LOWER() в SQLite работает только с ASCII: «РОЗА» и «роза» для него
# разные строки, и поиск по русским названиям молча не нашёл ничего.
# Нормализацию делает Python при загрузке каталога, а в базе лежат
# уже свёрнутые значения.
_ADDED_COLUMNS = {'name_key': "TEXT NOT NULL DEFAULT ''",
                  'search_key': "TEXT NOT NULL DEFAULT ''"}


def fold(value: Any) -> str:
    """Регистронезависимая форма строки для поиска."""
    return str(value or '').strip().casefold()


def catalog_items_from_package(payload: dict) -> list[dict[str, Any]]:
    """Каталог из `assets/data/data.json` пакета.

    Файл собирает платформа, но рантайм не обязан знать её формат
    целиком: здесь разбирается только устройство данных — источники с
    записями. Идентификаторы t1, t2… совпадают с теми, что ставит
    кнопка «В корзину», потому что оба считаются от порядка записей
    в источнике.

    Строки склеиваются для показа, а записи по полям нужны для поиска и
    цены, поэтому берутся `items`, а `rows` — только если их нет.
    """
    items: list[dict[str, Any]] = []
    sources = payload.values() if isinstance(payload, dict) else []
    for source in sources:
        if not isinstance(source, dict):
            continue
        records = source.get('items')
        if not isinstance(records, list) or not records:
            rows = source.get('rows')
            if isinstance(rows, list) and rows:
                records = [{'name': row} for row in rows]
            else:
                continue
        for record in records:
            if not isinstance(record, dict):
                continue
            name, price, search = _product_fields(record)
            items.append({'id': f't{len(items) + 1}', 'name': name,
                          'price': price, 'search': search})
    return items


def _product_fields(record: dict[str, Any]) -> tuple[str, float, str]:
    """Название, цена и поисковая строка из записи источника.

    Имена полей в источнике задаёт пользователь, поэтому берутся по
    очереди понятные имена. Цена должна быть числом: иначе корзина
    сложила бы строки.
    """
    name = ''
    price = 0.0
    search_parts: list[str] = []
    for key, value in record.items():
        folded = fold(key)
        if not name and folded in ('name', 'title', 'название', 'товар'):
            name = str(value or '')
            continue
        if folded in ('price', 'cost', 'цена', 'стоимость', 'amount'):
            try:
                price = float(str(value).replace(' ', '').replace(',', '.'))
            except (TypeError, ValueError):
                price = 0.0
            continue
        if value not in (None, ''):
            search_parts.append(str(value))
    return name or 'Товар', price, ' '.join([name] + search_parts)


def new_id(size: int = 6) -> str:
    """Короткий идентификатор заказа: вводится человеком вручную."""
    return secrets.token_hex(size // 2)


def new_sid() -> str:
    """Идентификатор сессии корзины."""
    return secrets.token_urlsafe(24)


class Store:
    """Тонкая обёртка над SQLite. Соединение одно на процесс."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._add_missing_columns()
            current = self._db.execute('PRAGMA user_version').fetchone()[0]
            if current == 0:
                self._db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
            elif current > SCHEMA_VERSION:
                # Более новый файл открыт старым рантаймом: писать в него
                # опасно, потерять данные — тем более. Отказ здесь
                # честнее, чем тихая порча заказов.
                raise RuntimeError(
                    f'Файл базы версии {current}, рантайм умеет {SCHEMA_VERSION}. '
                    'Обновите рантайм на сервере.'
                )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _add_missing_columns(self) -> None:
        """Дополняет таблицу каталога, если файл создан без них.

        Молча пропустить нельзя: поиск по русским названиям работал бы
        через раз, и это выглядело бы как «иногда не находит».
        """
        existing = {
            row['name'] for row in self._db.execute('PRAGMA table_info(catalog)')
        }
        for column, spec in _ADDED_COLUMNS.items():
            if column not in existing:
                self._db.execute(f'ALTER TABLE catalog ADD COLUMN {column} {spec}')

    # --- каталог -------------------------------------------------------

    def replace_catalog(self, items: list[dict[str, Any]]) -> int:
        rows = []
        for index, item in enumerate(items):
            name = str(item.get('name') or '')
            search = str(item.get('search') or name)
            rows.append((
                str(item.get('id') or ''),
                name,
                float(item.get('price') or 0),
                search,
                fold(name),
                fold(search),
                index,
            ))
        with self._lock:
            self._db.execute('DELETE FROM catalog')
            self._db.executemany(
                'INSERT INTO catalog (id, name, price, search, name_key,'
                ' search_key, position) VALUES (?, ?, ?, ?, ?, ?, ?)',
                rows,
            )
            self._db.commit()
        return len(rows)

    def catalog_size(self) -> int:
        row = self._db.execute('SELECT COUNT(*) FROM catalog').fetchone()
        return int(row[0])

    def find(self, needle: str) -> list[dict[str, Any]]:
        """Поиск по каталогу: начало слова, регистр не учитывается."""
        text = fold(needle)
        if not text:
            rows = self._db.execute(
                'SELECT id, name, price FROM catalog ORDER BY position LIMIT 20'
            ).fetchall()
        else:
            # Совпадение ищется в любом месте, но показывается вперёд то,
            # что начинается с запроса: «розы» должны оказаться выше
            # «букет роз». Порядок определяется сортировкой, а не тем,
            # что запрос случайно нашёлся.
            rows = self._db.execute(
                'SELECT id, name, price, search_key, name_key, position FROM catalog'
                ' WHERE search_key LIKE ? OR name_key LIKE ?'
                ' ORDER BY position LIMIT 50',
                (f'%{text}%', f'%{text}%'),
            ).fetchall()
            rows = sorted(
                rows,
                key=lambda r: (
                    0 if (r['name_key'].startswith(text)
                          or r['search_key'].startswith(text)) else 1,
                    r['position'],
                ),
            )
        return [
            {'id': r['id'], 'name': r['name'], 'price': float(r['price'])}
            for r in rows
        ]

    def item(self, item_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            'SELECT id, name, price FROM catalog WHERE id = ?', (item_id,)
        ).fetchone()
        if row is None:
            return None
        return {'id': row['id'], 'name': row['name'], 'price': float(row['price'])}

    # --- корзина -------------------------------------------------------

    def cart(self, sid: str) -> dict[str, Any]:
        row = self._db.execute(
            'SELECT payload FROM carts WHERE sid = ?', (sid,)
        ).fetchone()
        if row is None:
            return {'items': []}
        try:
            data = json.loads(row['payload'])
        except json.JSONDecodeError:
            return {'items': []}
        items = data.get('items') if isinstance(data, dict) else None
        return {'items': items if isinstance(items, list) else []}

    def save_cart(self, sid: str, items: list[dict[str, Any]]) -> None:
        payload = json.dumps({'items': items}, ensure_ascii=False)
        with self._lock:
            self._db.execute(
                'INSERT INTO carts (sid, payload, updated_at) VALUES (?, ?, ?)'
                ' ON CONFLICT(sid) DO UPDATE SET payload = excluded.payload,'
                ' updated_at = excluded.updated_at',
                (sid, payload, time.time()),
            )
            self._db.commit()

    # --- заказы --------------------------------------------------------

    def create_order(self, payload: dict[str, Any], total: float, items: int) -> str:
        order_id = new_id()
        with self._lock:
            self._db.execute(
                'INSERT INTO orders (id, payload, total, items, status, created_at)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (
                    order_id,
                    json.dumps(payload, ensure_ascii=False),
                    float(total),
                    int(items),
                    'new',
                    time.time(),
                ),
            )
            self._db.commit()
        return order_id

    def order(self, order_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            'SELECT id, total, items, status, created_at FROM orders WHERE id = ?',
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            'id': row['id'],
            'total': float(row['total']),
            'items': int(row['items']),
            'status': row['status'],
            'createdAt': int(row['created_at']),
        }

    def orders_total(self) -> int:
        return int(self._db.execute('SELECT COUNT(*) FROM orders').fetchone()[0])
