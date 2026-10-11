"""Каталог, карточка товара и цена — первый блок этапа 6.

Раньше все три выводились общими функциями: каталог и карточка давали
тот же список, что data.list, а цена — первую строку источника
целиком, вместе с названием товара.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from projects.export import render_block


def block_for(module: str, props: dict | None = None) -> dict:
    return {
        'id': 'b1',
        'module': module,
        'x': 0,
        'y': 0,
        'width': 640,
        'height': 320,
        'label': 'Блок',
        'props': props or {'source': 'src-1'},
    }


CATALOG = [
    {'name': 'Роза', 'cost': 1200, 'image': '/img/rose.jpg'},
    {'name': 'Тюльпан', 'cost': 900, 'image': '/img/tulip.jpg'},
    {'name': 'Лилия', 'cost': 1500, 'image': '/img/lily.jpg'},
]


class CatalogTests(SimpleTestCase):
    def test_products_are_cards(self):
        """Модуль давал список строк, а не карточки."""
        html = render_block(
            block_for('shop.catalog', {'titleField': 'name', 'priceField': 'cost'}),
            [], CATALOG,
        ).html
        self.assertEqual(html.count('class="product"'), 3)
        self.assertIn('product__title', html)

    def test_field_names_are_configurable(self):
        """В источнике имена полей произвольны."""
        html = render_block(
            block_for('shop.catalog', {'titleField': 'name', 'priceField': 'cost'}),
            [], CATALOG,
        ).html
        self.assertIn('Роза', html)
        self.assertIn('1200', html)

    def test_image_appears_when_field_set(self):
        html = render_block(
            block_for('shop.catalog', {
                'titleField': 'name', 'priceField': 'cost', 'imageField': 'image',
            }),
            [], CATALOG,
        ).html
        self.assertIn('/img/rose.jpg', html)
        self.assertIn('alt="Роза"', html)

    def test_placeholder_when_no_image_field(self):
        html = render_block(
            block_for('shop.catalog', {'titleField': 'name', 'priceField': 'cost'}),
            [], CATALOG,
        ).html
        self.assertNotIn('<img', html)
        self.assertIn('media__placeholder', html)

    def test_columns_reach_css(self):
        html = render_block(
            block_for('shop.catalog', {'titleField': 'name', 'columns': 4}), [], CATALOG
        ).html
        self.assertIn('--catalog-columns:4', html)

    def test_columns_are_bounded(self):
        html = render_block(
            block_for('shop.catalog', {'titleField': 'name', 'columns': 99}), [], CATALOG
        ).html
        self.assertIn('--catalog-columns:4', html)

    def test_limit_is_applied(self):
        html = render_block(
            block_for('shop.catalog', {'titleField': 'name', 'limit': 2}), [], CATALOG
        ).html
        self.assertEqual(html.count('class="product"'), 2)
        self.assertIn('Показано 2 из 3', html)

    def test_empty_catalog_says_so(self):
        html = render_block(block_for('shop.catalog', {'titleField': 'name'}), [], []).html
        self.assertIn('Каталог пуст', html)

    def test_no_external_images_by_default(self):
        """Картинки берутся из источника, а не из внешних сервисов."""
        html = render_block(
            block_for('shop.catalog', {'titleField': 'name', 'priceField': 'cost'}),
            [], CATALOG,
        ).html
        self.assertNotIn('http://', html)
        self.assertNotIn('https://', html)


class CardTests(SimpleTestCase):
    def test_card_takes_first_record(self):
        html = render_block(
            block_for('shop.card', {'titleField': 'name', 'priceField': 'cost'}),
            [], CATALOG,
        ).html
        self.assertIn('Роза', html)
        self.assertNotIn('Тюльпан', html)

    def test_detail_field_is_rendered(self):
        rows = [{'name': 'Роза', 'cost': 1200, 'about': 'Стойкая, 70 см'}]
        html = render_block(
            block_for('shop.card', {
                'titleField': 'name', 'priceField': 'cost', 'detailField': 'about',
            }),
            [], rows,
        ).html
        self.assertIn('Стойкая, 70 см', html)
        self.assertIn('product__detail', html)

    def test_price_prefix(self):
        html = render_block(
            block_for('shop.card', {
                'titleField': 'name', 'priceField': 'cost', 'pricePrefix': 'от',
            }),
            [], CATALOG,
        ).html
        self.assertIn('от 1200', html)

    def test_button_label(self):
        html = render_block(
            block_for('shop.card', {'titleField': 'name', 'buttonLabel': 'Купить'}),
            [], CATALOG,
        ).html
        self.assertIn('Купить', html)

    def test_empty_source_says_so(self):
        html = render_block(block_for('shop.card', {'titleField': 'name'}), [], []).html
        self.assertIn('Товар не выбран', html)


class PriceTests(SimpleTestCase):
    def test_only_price_field_is_shown(self):
        """Раньше выводилась строка целиком, вместе с названием."""
        html = render_block(
            block_for('shop.price', {'field': 'cost'}), [], [{'name': 'Роза', 'cost': 1200}]
        ).html
        self.assertIn('1200', html)
        self.assertNotIn('Роза', html)

    def test_currency_is_shown(self):
        html = render_block(
            block_for('shop.price', {'field': 'cost'}), [], [{'cost': 1200}]
        ).html
        self.assertIn('₽', html)

    def test_prefix(self):
        html = render_block(
            block_for('shop.price', {'field': 'cost', 'prefix': 'от'}), [], [{'cost': 900}]
        ).html
        self.assertIn('price__prefix', html)
        self.assertIn('от', html)

    def test_missing_price_gives_dash(self):
        """Ноль означал бы «цена нулевая», а её просто нет."""
        html = render_block(block_for('shop.price', {'field': 'cost'}), [], [{}]).html
        self.assertIn('—', html)

    def test_empty_source_gives_dash(self):
        html = render_block(block_for('shop.price', {'field': 'cost'}), [], []).html
        self.assertIn('—', html)

    def test_old_price_shown_when_asked(self):
        rows = [{'cost': 900}]
        html = render_block(
            block_for('shop.price', {
                'field': 'cost', 'showOld': True, 'oldValue': '1200',
            }),
            [], rows,
        ).html
        self.assertIn('price__old', html)
        self.assertIn('1200', html)

    def test_old_price_hidden_by_default(self):
        html = render_block(
            block_for('shop.price', {'field': 'cost', 'oldValue': '1200'}),
            [], [{'cost': 900}],
        ).html
        self.assertNotIn('price__old', html)