"""Тесты рантайма по протоколу из docs/RUNTIME.md.

Тесты не проверяют Django и платформу: рантайм поставляется отдельно и
не должен делить код с ними (ADR-0005). Общая точка проверки с платформой
— сам документ контракта, поэтому расхождение видно и там, и здесь.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.app import COOKIE, create_app
from runtime.catalog import CatalogLoader
from runtime.config import Config, load
from runtime.store import Store, catalog_items_from_package


class Client:
    """Минимальный вызов WSGI-приложения."""

    def __init__(self, app, origin: str | None = None, address: str = '10.0.0.1',
                 site_key: str = 'site-key-1'):
        self.app = app
        self.origin = origin
        self.address = address
        self.site_key = site_key
        self.cookies: dict[str, str] = {}

    def call(self, method: str, path: str, body: dict | None = None,
             query: str = '') -> tuple[int, dict]:
        raw = json.dumps(body).encode('utf-8') if body is not None else b''
        headers = [(b'CONTENT_LENGTH', str(len(raw)).encode())]
        if self.origin:
            headers.append((b'HTTP_ORIGIN', self.origin.encode()))
        headers.append((b'REMOTE_ADDR', self.address.encode()))
        if self.site_key:
            # По контракту заголовок обязателен на всех запросах, кроме
            # /health: тело запроса не всегда есть, а ключ нужен всегда.
            headers.append((b'HTTP_X_SITE_KEY', self.site_key.encode()))
        cookie = '; '.join(f'{k}={v}' for k, v in self.cookies.items())
        if cookie:
            headers.append((b'HTTP_COOKIE', cookie.encode()))

        environ = {
            'REQUEST_METHOD': method,
            'PATH_INFO': path,
            'QUERY_STRING': query,
            'REMOTE_ADDR': self.address,
            'CONTENT_TYPE': 'application/json',
            'wsgi.input': io.BytesIO(raw),
            'wsgi.url_scheme': 'http',
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': '8088',
            'SERVER_PROTOCOL': 'HTTP/1.1',
        }
        for key, value in headers:
            environ[key.decode()] = value.decode()

        captured: dict = {}

        def start_response(status, response_headers):
            captured['status'] = int(status.split()[0])
            captured['headers'] = response_headers

        chunks = self.app(environ, start_response)
        payload = json.loads(b''.join(chunks).decode('utf-8'))
        for name, value in captured['headers']:
            if name.lower() == 'set-cookie':
                key, _, rest = value.partition('=')
                self.cookies[key.strip()] = rest.split(';')[0]
        return captured['status'], payload


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Config({
            'version': 1,
            'siteKey': 'site-key-1',
            'secret': 'secret-1',
            'allowedOrigins': ['https://shop.example.ru'],
            'rateLimits': {'cartPerMinute': 3, 'searchPerMinute': 2},
        })
        self.store = Store(str(Path(self.tmp.name) / 'runtime.db'))
        self.addCleanup(self.store.close)
        self.app = create_app(self.config, self.store)
        self.client = Client(self.app)
        self.seed_catalog()

    def seed_catalog(self, items=None):
        return self.client.call('POST', '/catalog', {
            'siteKey': 'site-key-1',
            'items': items if items is not None else [
                {'id': 't1', 'name': 'Роза', 'price': 1200, 'search': 'роза цветок'},
                {'id': 't2', 'name': 'Тюльпан', 'price': 900, 'search': 'тюльпан луковица'},
                {'id': 't3', 'name': 'Лилия', 'price': 1500, 'search': 'лилия'},
            ],
        })

    def add(self, item_id='t1', qty=1):
        return self.client.call('POST', '/cart', {
            'siteKey': 'site-key-1', 'itemId': item_id, 'qty': qty,
        })


class HealthTests(RuntimeTestCase):
    def test_health_needs_no_key(self):
        status, body = self.client.call('GET', '/health')
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['ready'], True)

    def test_health_reports_protocol_version(self):
        """Клиент сверяет версию и отказывается подключаться при
        несовпадении — иначе он шлёт запросы в несовместимый формат."""
        _, body = self.client.call('GET', '/health')
        self.assertEqual(body['protocolVersion'], 1)

    def test_health_without_key_is_not_ready(self):
        """Без siteKey рантайм отвечает на health, но заказы не берёт."""
        store = Store(str(Path(self.tmp.name) / 'b.db'))
        self.addCleanup(store.close)
        _, body = Client(create_app(Config({'version': 1}), store)).call('GET', '/health')
        self.assertEqual(body['ready'], False)


class CatalogTests(RuntimeTestCase):
    def test_catalog_is_loaded(self):
        status, body = self.seed_catalog()
        self.assertEqual(status, 200)
        self.assertEqual(body['catalog'], 3)

    def test_foreign_site_key_is_refused(self):
        status, body = self.client.call('POST', '/catalog', {
            'siteKey': 'чужой', 'items': [],
        })
        self.assertEqual(status, 400)
        self.assertEqual(body['error'], 'bad_site_key')


class CartTests(RuntimeTestCase):
    def test_empty_cart_is_given_a_session(self):
        status, body = self.client.call('GET', '/cart')
        self.assertEqual(status, 200)
        self.assertEqual(body['cart']['items'], [])
        self.assertEqual(body['cart']['total'], 0)
        self.assertIn(COOKIE, self.client.cookies)

    def test_cart_survives_next_request(self):
        """Корзина переживает переход по ссылке — ради этого модуль и
        существует: состояние держит сервер, а не страница."""
        self.add('t1', 2)
        _, body = self.client.call('GET', '/cart')
        self.assertEqual(body['cart']['count'], 2)
        self.assertEqual(body['cart']['total'], 2400)

    def test_total_counts_every_item(self):
        self.add('t1', 1)
        self.add('t2', 1)
        _, body = self.client.call('GET', '/cart')
        self.assertEqual(body['cart']['total'], 2100)
        self.assertEqual(body['cart']['count'], 2)

    def test_price_comes_from_catalog(self):
        """Покупатель не присылает цену: иначе он прислал бы свою."""
        self.add('t1', 1)
        self.client.call('POST', '/cart', {
            'siteKey': 'site-key-1', 'itemId': 't1', 'qty': 1, 'price': 1,
        })
        _, body = self.client.call('GET', '/cart')
        self.assertEqual(body['cart']['items'][0]['price'], 1200)

    def test_qty_is_an_addition(self):
        """qty — прибавка, а не итоговое количество: об этом сказано в
        docs/RUNTIME.md, и клиент отправляет разницу."""
        self.add('t1', 2)
        self.add('t1', 1)
        _, body = self.client.call('GET', '/cart')
        self.assertEqual(body['cart']['items'][0]['qty'], 3)
        self.assertEqual(body['cart']['total'], 3600)

    def test_negative_qty_removes_one(self):
        self.add('t1', 3)
        self.add('t1', -1)
        _, body = self.client.call('GET', '/cart')
        self.assertEqual(body['cart']['items'][0]['qty'], 2)

    def test_zero_qty_removes_item(self):
        self.add('t1', 2)
        self.add('t1', 0)
        _, body = self.client.call('GET', '/cart')
        self.assertEqual(body['cart']['items'], [])

    def test_absurd_decrease_is_refused(self):
        """−999 в одном запросе — это не «убрать одну позицию», а мусор."""
        self.add('t1', 2)
        status, body = self.add('t1', -999)
        self.assertEqual(status, 400)
        self.assertEqual(body['error'], 'bad_qty')

    def test_unknown_item_is_refused(self):
        status, body = self.add('нет-такого', 1)
        self.assertEqual(status, 400)
        self.assertEqual(body['error'], 'unknown_item')

    def test_foreign_cookie_is_ignored(self):
        """Подделка чужой корзины: идентификатор без верной подписи
        не даёт доступа к её содержимому."""
        self.add('t1', 1)
        other = Client(self.app)
        other.cookies[COOKIE] = self.client.cookies[COOKIE].split('.')[0] + '. подделка'
        _, body = other.call('GET', '/cart')
        self.assertEqual(body['cart']['items'], [])

    def test_limit_is_answered_not_silently_ignored(self):
        """Молчаливое ограничение выглядело бы как «сайт сломался»."""
        statuses = [self.add('t1', 1)[0] for _ in range(5)]
        self.assertIn(429, statuses)

    def test_origin_is_checked(self):
        """Запрос с чужого домена отвергается, а не «ну как получится»."""
        stranger = Client(self.app, origin='https://чужик.example')
        status, body = stranger.call('GET', '/cart')
        self.assertEqual(status, 403)
        self.assertEqual(body['error'], 'bad_origin')


class CheckoutTests(RuntimeTestCase):
    def test_order_gets_number_and_clears_cart(self):
        self.add('t1', 2)
        status, body = self.client.call('POST', '/checkout', {
            'siteKey': 'site-key-1', 'name': 'Ирина', 'phone': '+7 900',
            'consent': True,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body['order']['total'], 2400)
        self.assertEqual(body['order']['items'], 2)
        self.assertTrue(body['order']['id'])

        _, cart = self.client.call('GET', '/cart')
        self.assertEqual(cart['cart']['items'], [])

    def test_order_is_readable_by_number(self):
        self.add('t1', 1)
        _, body = self.client.call('POST', '/checkout', {
            'siteKey': 'site-key-1', 'name': 'Ирина', 'phone': '+7 900',
            'consent': True,
        })
        order_id = body['order']['id']
        status, found = self.client.call('GET', f'/checkout/{order_id}')
        self.assertEqual(status, 200)
        self.assertEqual(found['order']['id'], order_id)

    def test_unknown_order_is_404(self):
        status, body = self.client.call('GET', '/checkout/нетакого')
        self.assertEqual(status, 404)

    def test_consent_is_required(self):
        """Без согласия на обработку данных заказ не принимается."""
        self.add('t1', 1)
        status, body = self.client.call('POST', '/checkout', {
            'siteKey': 'site-key-1', 'name': 'Ирина', 'phone': '+7 900',
            'consent': False,
        })
        self.assertEqual(status, 400)
        self.assertEqual(body['error'], 'no_consent')
        self.assertEqual(self.store.orders_total(), 0)

    def test_empty_cart_is_refused(self):
        status, body = self.client.call('POST', '/checkout', {
            'siteKey': 'site-key-1', 'name': 'Ирина', 'phone': '+7 900',
            'consent': True,
        })
        self.assertEqual(status, 400)
        self.assertEqual(body['error'], 'empty_cart')

    def test_name_and_phone_are_required(self):
        self.add('t1', 1)
        status, body = self.client.call('POST', '/checkout', {
            'siteKey': 'site-key-1', 'name': '', 'consent': True,
        })
        self.assertEqual(status, 400)
        self.assertEqual(body['error'], 'missing_fields')

    def test_long_comment_is_cut(self):
        self.add('t1', 1)
        self.client.call('POST', '/checkout', {
            'siteKey': 'site-key-1', 'name': 'Ирина', 'phone': '+7 900',
            'comment': 'я' * 2500, 'consent': True,
        })
        row = self.store._db.execute('SELECT payload FROM orders').fetchone()
        self.assertLessEqual(len(json.loads(row['payload'])['comment']), 2000)

    def test_oversized_body_is_refused(self):
        """Тело больше 16 КБ не читается целиком: иначе сервер держал бы
        в памяти запрос, который всё равно отвергнет."""
        self.add('t1', 1)
        status, body = self.client.call('POST', '/checkout', {
            'siteKey': 'site-key-1', 'name': 'Ирина', 'phone': '+7 900',
            'comment': 'я' * 20000, 'consent': True,
        })
        self.assertEqual(status, 400)
        self.assertEqual(self.store.orders_total(), 0)


class SearchTests(RuntimeTestCase):
    def test_finds_by_word(self):
        status, body = self.client.call('GET', '/search', query='q=роза')
        self.assertEqual(status, 200)
        self.assertEqual([i['id'] for i in body['items']], ['t1'])

    def test_case_is_ignored(self):
        _, body = self.client.call('GET', '/search', query='q=РОЗА')
        self.assertEqual([i['id'] for i in body['items']], ['t1'])

    def test_case_is_ignored_in_cyrillic(self):
        """SQLite сворачивает регистр только для ASCII: «РОЗА» и «роза»
        для него разные строки. Без нормализации в Python поиск по
        русским названиям молча ничего не находил."""
        _, body = self.client.call('GET', '/search', query='q=РОЗА')
        self.assertEqual([i['id'] for i in body['items']], ['t1'])

    def test_cyrillic_found_by_casefold(self):
        _, body = self.client.call('GET', '/search', query='q=роза')
        self.assertEqual([i['id'] for i in body['items']], ['t1'])

    def test_finds_inside_search_field(self):
        _, body = self.client.call('GET', '/search', query='q=луковица')
        self.assertEqual([i['id'] for i in body['items']], ['t2'])

    def test_empty_query_returns_start_of_catalog(self):
        """Пустой результат по пустому запросу не объясняет, что поиск
        вообще работает."""
        _, body = self.client.call('GET', '/search', query='q=')
        self.assertEqual(len(body['items']), 3)

    def test_missing_query_is_not_an_error(self):
        status, body = self.client.call('GET', '/search')
        self.assertEqual(status, 200)
        self.assertEqual(len(body['items']), 3)

    def test_search_is_limited(self):
        statuses = [self.client.call('GET', '/search', query='q=а')[0] for _ in range(4)]
        self.assertIn(429, statuses)


class RoutingTests(RuntimeTestCase):
    def test_unknown_path_is_404(self):
        status, _ = self.client.call('GET', '/нет-такого')
        self.assertEqual(status, 404)

    def test_wrong_method_is_405(self):
        status, _ = self.client.call('DELETE', '/cart')
        self.assertEqual(status, 405)

    def test_trailing_slash_does_not_break_route(self):
        status, _ = self.client.call('GET', '/cart/')
        self.assertEqual(status, 200)

    def test_broken_json_is_rejected(self):
        app_environ = {
            'REQUEST_METHOD': 'POST', 'PATH_INFO': '/cart',
            'CONTENT_LENGTH': '5', 'REMOTE_ADDR': '10.0.0.2',
            'wsgi.input': io.BytesIO(b'{tru__'), 'wsgi.url_scheme': 'http',
        }
        status = {}

        def start_response(value, headers):
            status['code'] = int(value.split()[0])

        self.app(app_environ, start_response)
        self.assertEqual(status['code'], 400)


class CatalogFromPackageTests(unittest.TestCase):
    """Каталог берётся из данных пакета.

    Заказчик не должен вести список товаров параллельно сборке сайта,
    а идентификаторы обязаны совпадать с кнопками «В корзину».
    """

    PACKAGE = {
        'src-1': {
            'rows': ['Роза · 1200'],
            'items': [
                {'name': 'Роза', 'cost': 1200},
                {'name': 'Тюльпан', 'cost': 900},
            ],
        },
    }

    def test_ids_match_add_buttons(self):
        items = catalog_items_from_package(self.PACKAGE)
        self.assertEqual([i['id'] for i in items], ['t1', 't2'])

    def test_name_and_price_are_found(self):
        items = catalog_items_from_package(self.PACKAGE)
        self.assertEqual(items[0]['name'], 'Роза')
        self.assertEqual(items[0]['price'], 1200)

    def test_comma_is_read_as_decimal_separator(self):
        items = catalog_items_from_package({
            's': {'items': [{'название': 'Роза', 'цена': '1200,50'}]},
        })
        self.assertEqual(items[0]['price'], 1200.50)

    def test_price_text_does_not_break_cart(self):
        """Нечисловая цена обнуляется, а не роняет сервис: иначе одна
        строка в источнике ломала бы счёт корзины."""
        items = catalog_items_from_package({
            's': {'items': [{'name': 'X', 'price': 'по запросу'}]},
        })
        self.assertEqual(items[0]['price'], 0.0)

    def test_rows_are_used_when_items_missing(self):
        items = catalog_items_from_package({'s': {'rows': ['Роза', 'Тюльпан']}})
        self.assertEqual([i['name'] for i in items], ['Роза', 'Тюльпан'])

    def test_empty_package_gives_empty_catalog(self):
        self.assertEqual(catalog_items_from_package({}), [])
        self.assertEqual(catalog_items_from_package({'s': {}}), [])


class CatalogLoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(str(Path(self.tmp.name) / 'runtime.db'))
        self.addCleanup(self.store.close)

    def test_unreachable_url_keeps_catalog(self):
        """Сайт должен жить и с устаревшим каталогом."""
        self.store.replace_catalog([{'id': 't1', 'name': 'Роза', 'price': 100}])
        loader = CatalogLoader('http://127.0.0.1:9/нет-такого.json', self.store)
        self.assertEqual(loader.load(), 0)
        self.assertEqual(self.store.item('t1')['name'], 'Роза')

    def test_package_is_loaded_over_http(self):
        import http.server
        import threading

        body = json.dumps(CatalogFromPackageTests.PACKAGE).encode('utf-8')

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)

        url = f'http://127.0.0.1:{server.server_port}/assets/data/data.json'
        count = CatalogLoader(url, self.store).load()
        self.assertEqual(count, 2)
        self.assertEqual(self.store.item('t2')['name'], 'Тюльпан')


class ConfigTests(unittest.TestCase):
    def test_first_run_creates_config_with_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load(Path(tmp) / 'runtime.json')
            self.assertTrue(config.ready)
            self.assertTrue((Path(tmp) / 'runtime.json').exists())

    def test_secret_differs_between_installations(self):
        """Два магазина на одном хостинге не должны делить подпись cookie."""
        secrets = set()
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                secrets.add(load(Path(tmp) / 'runtime.json').secret)
        self.assertEqual(len(secrets), 2)

    def test_existing_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime.json'
            path.write_text(json.dumps({'siteKey': 'k', 'secret': 's'}), encoding='utf-8')
            config = load(path)
            self.assertEqual(config.site_key, 'k')


if __name__ == '__main__':
    unittest.main()
