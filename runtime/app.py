"""WSGI-приложение рантайма.

Приложение не знает, как его запускают: встроенным сервером на порту,
gunicorn или uwsgi на shared-хостинге. Всё, что нужно, — функция
`create_app`, возвращающая WSGI-callable.

Порядок проверок не случаен: лимиты и Origin идут до чтения тела, иначе
сервер тратил бы память на запросы, которые всё равно отвергнуты.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import time
from collections import defaultdict
from typing import Any, Callable
from urllib.parse import parse_qs

from . import PROTOCOL_VERSION
from .config import Config
from .store import Store, new_sid

log = logging.getLogger('runtime')

COOKIE = 'auracart'
MAX_QTY = 999
MAX_NAME = 120
MAX_PHONE = 40
MAX_COMMENT = 2000

REASONS = {
    200: 'OK',
    400: 'Bad Request',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    429: 'Too Many Requests',
    500: 'Internal Server Error',
}


class Limit:
    """Скользящее окно в минуту по адресу.

    Словарь, а не внешнее хранилище: рантайм живёт на одной машине, и
    сбрасывать счётчики при перезапуске не жалко.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    def take(self, key: str) -> bool:
        now = time.time()
        hits = [t for t in self._hits[key] if now - t < 60]
        if len(hits) >= self.per_minute:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


def _cookie(environ: dict, name: str) -> str | None:
    raw = environ.get('HTTP_COOKIE') or ''
    for part in raw.split(';'):
        key, _, value = part.strip().partition('=')
        if key == name:
            return value
    return None


class App:
    def __init__(self, config: Config, store: Store) -> None:
        self.config = config
        self.store = store
        self.cart_limit = Limit(config.cart_per_minute)
        self.search_limit = Limit(config.search_per_minute)

    # --- подпись cookie ------------------------------------------------

    def sign(self, sid: str) -> str:
        mac = hmac.new(
            self.config.secret.encode('utf-8'), sid.encode('utf-8'), hashlib.sha256
        )
        return hmac.new(mac.digest(), b'cart', hashlib.sha256).hexdigest()[:32]

    def cookie_value(self, sid: str) -> str:
        return f'{sid}.{self.sign(sid)}'

    def sid_from(self, raw: str | None) -> str | None:
        """Возвращает sid только если подпись верна."""
        if not raw or '.' not in raw:
            return None
        sid, _, signature = raw.rpartition('.')
        if not sid:
            return None
        if not hmac.compare_digest(signature.encode('utf-8'), self.sign(sid).encode('utf-8')):
            return None
        return sid

    def cookie_header(self, sid: str) -> str:
        # HttpOnly: идентификатор сессии не должен читаться скриптами
        # страницы. SameSite=Lax: переход со стороннего сайта не должен
        # приносить чужую корзину.
        return f'{COOKIE}={self.cookie_value(sid)}; Path=/; HttpOnly; SameSite=Lax'

    # --- ответы --------------------------------------------------------

    def respond(
        self,
        start: Callable[[str, list[tuple[str, str]]], Any],
        status: int,
        payload: dict,
        extra: list[tuple[str, str]] | None = None,
    ) -> list[bytes]:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(body))),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'no-store'),
        ]
        headers.extend(extra or [])
        start(f'{status} {REASONS.get(status, "OK")}', headers)
        return [body]

    def ok(self, start, payload: dict, extra=None) -> list[bytes]:
        return self.respond(start, 200, {'ok': True, **payload}, extra)

    def bad(self, start, code: str, message: str, status: int = 400) -> list[bytes]:
        return self.respond(start, status, {'ok': False, 'error': code,
                                            'message': message})

    # --- проверки запроса -----------------------------------------------

    def read_json(self, environ: dict) -> tuple[dict | None, str | None]:
        try:
            length = int(environ.get('CONTENT_LENGTH') or 0)
        except ValueError:
            return None, 'неверная длина запроса'
        if length > self.config.max_body_bytes:
            return None, 'тело запроса слишком велико'
        if length <= 0:
            return {}, None
        raw = environ['wsgi.input'].read(length)
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, 'тело запроса не является JSON'
        if not isinstance(data, dict):
            return None, 'ожидался объект JSON'
        return data, None

    def check_site_key(self, environ: dict, data: dict | None = None) -> str | None:
        key = (data or {}).get('siteKey') or environ.get('HTTP_X_SITE_KEY')
        if not key:
            return 'не передан siteKey'
        # compare_digest не принимает не-ASCII строки: ключ заказчика
        # русским быть может, а сравнение обязано быть постоянным по времени.
        if not hmac.compare_digest(
            str(key).encode('utf-8'), self.config.site_key.encode('utf-8')
        ):
            return 'чужой siteKey'
        return None

    def check_origin(self, environ: dict) -> str | None:
        origin = environ.get('HTTP_ORIGIN')
        if not origin or not self.config.allowed_origins:
            # Пустой список — режим первого запуска: проверять нечего.
            return None
        if str(origin).rstrip('/') not in self.config.allowed_origins:
            return 'запрос с чужого домена'
        return None

    @staticmethod
    def client_key(environ: dict) -> str:
        return environ.get('REMOTE_ADDR') or 'unknown'

    def cart_payload(self, sid: str) -> dict:
        cart = self.store.cart(sid)
        items: list[dict] = []
        total = 0.0
        count = 0
        for entry in cart.get('items', []):
            if not isinstance(entry, dict):
                continue
            qty = int(entry.get('qty') or 0)
            price = float(entry.get('price') or 0)
            items.append({'id': entry.get('id'), 'name': entry.get('name'),
                          'price': price, 'qty': qty})
            total += price * qty
            count += qty
        return {'items': items, 'total': total, 'count': count}

    # --- маршруты ------------------------------------------------------

    def health(self, start) -> list[bytes]:
        return self.ok(start, {
            'service': 'aurabuilder-runtime',
            'runtimeVersion': PROTOCOL_VERSION,
            'protocolVersion': PROTOCOL_VERSION,
            'ready': self.config.ready,
            'catalog': self.store.catalog_size(),
            'orders': self.store.orders_total(),
        })

    def get_cart(self, environ, start) -> list[bytes]:
        sid = self.sid_from(_cookie(environ, COOKIE))
        extra: list[tuple[str, str]] = []
        if sid is None:
            sid = new_sid()
            extra.append(('Set-Cookie', self.cookie_header(sid)))
        return self.ok(start, {'cart': self.cart_payload(sid)}, extra)

    def post_cart(self, environ, start) -> list[bytes]:
        if not self.cart_limit.take(self.client_key(environ)):
            return self.bad(start, 'rate_limited',
                            'Слишком много запросов. Повторите позже.', 429)
        data, problem = self.read_json(environ)
        if problem:
            return self.bad(start, 'bad_request', problem)
        problem = self.check_site_key(environ, data)
        if problem:
            return self.bad(start, 'bad_site_key', problem)

        payload = data or {}
        item_id = str(payload.get('itemId') or '')
        try:
            qty = int(payload.get('qty', 1))
        except (TypeError, ValueError):
            return self.bad(start, 'bad_qty', 'Количество должно быть числом')
        if qty < 0:
            return self.bad(start, 'bad_qty',
                            'Отрицательное количество означало бы минус к оплате')

        sid = self.sid_from(_cookie(environ, COOKIE)) or new_sid()
        items = [i for i in self.store.cart(sid).get('items', [])
                 if isinstance(i, dict)]

        if qty == 0:
            items = [i for i in items if i.get('id') != item_id]
        else:
            found = self.store.item(item_id)
            if found is None:
                return self.bad(start, 'unknown_item', 'Товар не найден в каталоге')
            entry = next((i for i in items if i.get('id') == item_id), None)
            if entry is None:
                entry = {'id': found['id'], 'name': found['name'],
                         'price': found['price'], 'qty': 0}
                items.append(entry)
            entry['qty'] = min(MAX_QTY, int(entry.get('qty') or 0) + qty)
            # Цена и название берутся из каталога, а не из запроса:
            # иначе покупатель присылал бы свою цену.
            entry['price'] = found['price']
            entry['name'] = found['name']

        self.store.save_cart(sid, items)
        return self.ok(start, {'cart': self.cart_payload(sid)},
                       [('Set-Cookie', self.cookie_header(sid))])

    def post_checkout(self, environ, start) -> list[bytes]:
        data, problem = self.read_json(environ)
        if problem:
            return self.bad(start, 'bad_request', problem)
        problem = self.check_site_key(environ, data)
        if problem:
            return self.bad(start, 'bad_site_key', problem)
        payload = data or {}

        # Согласие проверяется до остального: без него заказ принимать
        # нельзя (ТЗ п.9.1), и записать его в базу молча значило бы
        # собрать данные без правового основания.
        if payload.get('consent') is not True:
            return self.bad(start, 'no_consent',
                            'Нужно согласие на обработку персональных данных')

        sid = self.sid_from(_cookie(environ, COOKIE)) or new_sid()
        cart = self.cart_payload(sid)
        if not cart['items']:
            return self.bad(start, 'empty_cart', 'Корзина пуста')

        name = str(payload.get('name') or '')[:MAX_NAME].strip()
        phone = str(payload.get('phone') or '')[:MAX_PHONE].strip()
        if not name or not phone:
            return self.bad(start, 'missing_fields', 'Нужны имя и телефон')

        order_id = self.store.create_order({
            'name': name,
            'phone': phone,
            'comment': str(payload.get('comment') or '')[:MAX_COMMENT],
            'items': cart['items'],
        }, cart['total'], cart['count'])
        self.store.save_cart(sid, [])
        return self.ok(start, {'order': {'id': order_id, 'total': cart['total'],
                                         'items': cart['count'], 'status': 'new'}},
                       [('Set-Cookie', self.cookie_header(sid))])

    def get_order(self, environ, start, order_id: str) -> list[bytes]:
        problem = self.check_site_key(environ)
        if problem:
            return self.bad(start, 'bad_site_key', problem)
        order = self.store.order(order_id)
        if order is None:
            return self.bad(start, 'not_found', 'Заказ не найден', 404)
        return self.ok(start, {'order': order})

    def get_search(self, environ, start, query: str) -> list[bytes]:
        if not self.search_limit.take(self.client_key(environ)):
            return self.bad(start, 'rate_limited', 'Слишком много запросов', 429)
        problem = self.check_site_key(environ)
        if problem:
            return self.bad(start, 'bad_site_key', problem)
        return self.ok(start, {'items': self.store.find(query), 'query': query})

    def post_catalog(self, environ, start) -> list[bytes]:
        data, problem = self.read_json(environ)
        if problem:
            return self.bad(start, 'bad_request', problem)
        problem = self.check_site_key(environ, data)
        if problem:
            return self.bad(start, 'bad_site_key', problem)
        items = (data or {}).get('items')
        if not isinstance(items, list):
            return self.bad(start, 'bad_request', 'Ожидался список items')
        clean = [
            {
                'id': str(i.get('id') or ''),
                'name': str(i.get('name') or ''),
                'price': i.get('price') or 0,
                'search': str(i.get('search') or ''),
            }
            for i in items
            if isinstance(i, dict) and str(i.get('id') or '')
        ]
        return self.ok(start, {'catalog': self.store.replace_catalog(clean)})

    # --- WSGI ----------------------------------------------------------

    def __call__(self, environ, start_response) -> list[bytes]:
        method = environ.get('REQUEST_METHOD', 'GET').upper()
        path = (environ.get('PATH_INFO') or '/').rstrip('/') or '/'

        def start(status: str, headers: list[tuple[str, str]]) -> None:
            start_response(status, headers)

        try:
            if path == '/health':
                return self.health(start)

            problem = self.check_origin(environ)
            if problem:
                return self.bad(start, 'bad_origin', problem, 403)

            if path == '/cart':
                if method == 'GET':
                    return self.get_cart(environ, start)
                if method == 'POST':
                    return self.post_cart(environ, start)
                return self.bad(start, 'method', 'Метод не поддерживается', 405)

            if path == '/checkout' and method == 'POST':
                return self.post_checkout(environ, start)

            if path.startswith('/checkout/') and method == 'GET':
                return self.get_order(environ, start, path.rsplit('/', 1)[-1])

            if path == '/catalog' and method == 'POST':
                return self.post_catalog(environ, start)

            if path == '/search' and method == 'GET':
                query = (parse_qs(environ.get('QUERY_STRING') or '').get('q') or [''])[0]
                return self.get_search(environ, start, query)

            return self.bad(start, 'not_found', 'Метод не найден', 404)
        except Exception:  # noqa: BLE001 — рантайм не должен падать на живом сайте
            log.exception('внутренняя ошибка рантайма')
            return self.bad(start, 'server_error', 'Внутренняя ошибка рантайма', 500)


def create_app(config: Config, store: Store) -> App:
    return App(config, store)
