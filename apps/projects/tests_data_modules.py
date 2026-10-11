"""Модули вычислений: счётчик, агрегат, фильтр, сортировка, связанные, форма.

Раньше эти модули не вычисляли ничего: агрегат складывал все цифры
из всех полей записи (телефон попадал в сумму заказа), сортировка и
фильтр просто показывали весь набор и подпись, что «заработает
после подключения бэкенда».

Теперь условие известно на этапе сборки, и статическому пакету оно
ни к чему — пакет и есть результат.
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
    {'title': 'Роза', 'price': 1200, 'phone': '999'},
    {'title': 'Тюльпан', 'price': 900, 'phone': '888'},
    {'title': 'Лилия', 'price': 1500, 'phone': '777'},
]


class AggregateTests(SimpleTestCase):
    def test_sums_only_chosen_field(self):
        html = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'sum'}),
            [],
            CATALOG,
        ).html
        self.assertIn('3600', html.replace(' ', ''))

    def test_ignores_numbers_from_other_fields(self):
        """Цифры телефонов не должны попадать в сумму цен."""
        html = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'sum'}),
            [],
            CATALOG,
        ).html
        self.assertNotIn('6272', html.replace(' ', ''))

    def test_average(self):
        html = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'avg'}),
            [],
            CATALOG,
        ).html
        self.assertIn('1200', html.replace(' ', ''))

    def test_min_and_max(self):
        low = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'min'}), [], CATALOG
        ).html
        high = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'max'}), [], CATALOG
        ).html
        self.assertIn('900', low.replace(' ', ''))
        self.assertIn('1500', high.replace(' ', ''))

    def test_count_does_not_need_values(self):
        html = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'count'}),
            [],
            CATALOG,
        ).html
        self.assertIn('3', html)

    def test_empty_field_gives_dash_not_zero(self):
        """Ноль означал бы «посчитали и ничего не нашли»."""
        html = render_block(
            block_for('data.aggregate', {'field': 'absent', 'op': 'sum'}), [], CATALOG
        ).html
        self.assertIn('—', html)

    def test_suffix_is_shown(self):
        html = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'sum', 'suffix': '₽'}),
            [],
            CATALOG,
        ).html
        self.assertIn('₽', html)

    def test_number_has_no_trailing_zeros(self):
        html = render_block(
            block_for('data.aggregate', {'field': 'price', 'op': 'sum'}), [],
            [{'price': 1200.50}],
        ).html
        self.assertIn('1200.5', html)


class FilterTests(SimpleTestCase):
    def test_equality_filters_rows(self):
        html = render_block(
            block_for('data.filter', {'field': 'title', 'operator': 'eq', 'value': 'Роза'}),
            [],
            CATALOG,
        ).html
        self.assertIn('Роза', html)
        self.assertNotIn('Тюльпан', html)

    def test_contains_filters_rows(self):
        html = render_block(
            block_for('data.filter', {'field': 'title', 'operator': 'contains', 'value': 'и'}),
            [],
            CATALOG,
        ).html
        # Буква «и» есть только в «Лилия»: «Роза» и «Тюльпан» мимо.
        self.assertIn('Отобрано 1 из 3', html)
        self.assertIn('Лилия', html)

    def test_greater_than_uses_numbers(self):
        html = render_block(
            block_for('data.filter', {'field': 'price', 'operator': 'gt', 'value': '1000'}),
            [],
            CATALOG,
        ).html
        self.assertIn('Отобрано 2 из 3', html)

    def test_no_backend_note_needed(self):
        """Фильтр выполняется при сборке, а не «после бэкенда»."""
        html = render_block(
            block_for('data.filter', {'field': 'title', 'operator': 'eq', 'value': 'Роза'}),
            [],
            CATALOG,
        ).html
        self.assertNotIn('после подключения бэкенда', html)

    def test_empty_value_keeps_filled_rows(self):
        html = render_block(
            block_for('data.filter', {'field': 'title', 'operator': 'eq', 'value': ''}),
            [],
            CATALOG,
        ).html
        self.assertIn('Отобрано 3 из 3', html)


class SortTests(SimpleTestCase):
    def test_ascending(self):
        html = render_block(
            block_for('data.sort', {'field': 'price', 'direction': 'asc'}), [], CATALOG
        ).html
        self.assertLess(html.index('900'), html.index('1500'))

    def test_descending(self):
        html = render_block(
            block_for('data.sort', {'field': 'price', 'direction': 'desc'}), [], CATALOG
        ).html
        self.assertLess(html.index('1500'), html.index('900'))

    def test_text_sorted_alphabetically(self):
        rows = [{'title': 'Яблоко'}, {'title': 'Абрикос'}, {'title': 'Вишня'}]
        html = render_block(
            block_for('data.sort', {'field': 'title', 'direction': 'asc'}), [], rows
        ).html
        self.assertLess(html.index('Абрикос'), html.index('Вишня'))

    def test_limit_is_applied(self):
        html = render_block(
            block_for('data.sort', {'field': 'price', 'direction': 'asc', 'limit': 2}),
            [],
            CATALOG,
        ).html
        self.assertIn('Показано 2 из 3', html)

    def test_limit_is_bounded(self):
        html = render_block(
            block_for('data.sort', {'field': 'price', 'direction': 'asc', 'limit': 9999}),
            [],
            CATALOG,
        ).html
        self.assertIn('Показано 3 из 3', html)


class CountTests(SimpleTestCase):
    def test_counts_records(self):
        html = render_block(block_for('data.count'), [], CATALOG).html
        self.assertIn('>3<', html)

    def test_counts_only_filled_field(self):
        rows = [{'title': 'Роза', 'note': ''}, {'title': 'Тюльпан', 'note': 'x'}]
        html = render_block(block_for('data.count', {'field': 'note'}), [], rows).html
        self.assertIn('>1<', html)

    def test_label_comes_from_props(self):
        html = render_block(block_for('data.count', {'label': 'Товаров'}), [], CATALOG).html
        self.assertIn('Товаров', html)

    def test_falls_back_to_rows_without_dataset(self):
        """Коммерческие блоки передают строки, а не записи по полям."""
        html = render_block(block_for('data.count'), ['a', 'b', 'c']).html
        self.assertIn('>3<', html)


class RelatedTests(SimpleTestCase):
    def test_cards_use_title_field(self):
        html = render_block(
            block_for('data.related', {'titleField': 'title', 'limit': 4}), [], CATALOG
        ).html
        self.assertIn('Роза', html)
        self.assertEqual(html.count('related__card'), 3)

    def test_limit_is_applied(self):
        html = render_block(
            block_for('data.related', {'titleField': 'title', 'limit': 1}), [], CATALOG
        ).html
        self.assertEqual(html.count('related__card'), 1)


class DataFormTests(SimpleTestCase):
    def test_fields_come_from_props(self):
        """Названия полей — из свойства, а не из ключей записи.

        В источнике ключи title и phone, а в форме нужны подписи,
        которые задаёт пользователь.
        """
        html = render_block(
            block_for('data.form', {'fields': 'Имя;Телефон'}), [], CATALOG
        ).html
        self.assertIn('Имя', html)
        self.assertIn('Телефон', html)
        self.assertNotIn('>title<', html)

    def test_submit_label_comes_from_props(self):
        html = render_block(
            block_for('data.form', {'fields': 'Имя', 'submitLabel': 'Отправить заявку'}),
            [],
            CATALOG,
        ).html
        self.assertIn('Отправить заявку', html)

    def test_says_backend_is_needed(self):
        """Форма только собирает значения: отправлять некуда."""
        html = render_block(block_for('data.form', {'fields': 'Имя'}), [], CATALOG).html
        self.assertIn('после подключения бэкенда', html)

    def test_custom_note_replaces_default(self):
        html = render_block(
            block_for('data.form', {'fields': 'Имя', 'note': 'Позвоним в течение дня'}),
            [],
            CATALOG,
        ).html
        self.assertIn('Позвоним в течение дня', html)
        self.assertNotIn('после подключения бэкенда', html)