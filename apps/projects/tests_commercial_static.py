"""Баннер, тарифы, сравнение, отзывы, остаток и заявка.

Эти шесть модулей обслуживают коммерческую страницу и раньше
выводились общими функциями: баннер не отличался от обычной секции,
тарифы шли списком строк, отзывы теряли автора и оценку, остаток
выглядел как обычный счётчик, а заявка не сказала, куда уйдут данные.
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
        'props': props or {},
    }


def html_for(module: str, props: dict | None = None, dataset: list[dict] | None = None) -> str:
    return render_block(block_for(module, props), [], dataset or []).html


class PromoBannerTests(SimpleTestCase):
    def test_banner_has_action(self):
        """Баннер без кнопки — это просто секция с заголовком."""
        html = html_for('promo.banner', {
            'heading': 'Лето со скидками',
            'text': 'Скидка 20% до конца месяца',
            'buttonLabel': 'Смотреть каталог',
            'buttonLink': '/catalog',
        })
        self.assertIn('banner__action', html)
        self.assertIn('href="/catalog"', html)
        self.assertIn('Смотреть каталог', html)

    def test_banner_is_told_apart_by_fill(self):
        """Отличие от обычной секции должно быть заметно, а не в коде."""
        html = html_for('promo.banner', {'heading': 'Акция', 'background': 'accent'})
        self.assertIn('banner--accent', html)

    def test_banner_escapes_link(self):
        html = html_for('promo.banner', {
            'buttonLabel': 'Жми', 'buttonLink': '/a"><script>x</script>',
        })
        self.assertNotIn('<script>', html)


class PricingTests(SimpleTestCase):
    PLANS = [
        {'plan': 'Старт', 'cost': 0, 'term': 'месяц',
         'bullets': 'Сайт на 5 страниц;Почта поддержки'},
        {'plan': 'Бизнес', 'cost': 2500, 'term': 'месяц',
         'bullets': 'Сайт на 50 страниц;Поддержка 24/7', 'pick': '1'},
    ]

    def test_plans_are_cards(self):
        """Тарифы шли обычным списком: выбрать один было нельзя."""
        html = html_for('promo.pricing', {
            'titleField': 'plan',
            'priceField': 'cost',
            'periodField': 'term',
            'featuresField': 'bullets',
            'highlight': 'pick',
        }, self.PLANS)
        self.assertEqual(html.count('<article class="plan'), 2)
        self.assertIn('plan__price', html)
        self.assertIn('plan__period', html)

    def test_features_are_list(self):
        html = html_for('promo.pricing', {
            'titleField': 'plan', 'featuresField': 'bullets',
        }, self.PLANS)
        self.assertIn('<li>Сайт на 5 страниц</li>', html)
        self.assertIn('<li>Поддержка 24/7</li>', html)

    def test_chosen_plan_is_marked(self):
        html = html_for('promo.pricing', {
            'titleField': 'plan', 'highlight': 'pick',
        }, self.PLANS)
        self.assertEqual(html.count('plan--highlight'), 1)
        self.assertIn('Бизнес', html)

    def test_empty_pricing_says_so(self):
        html = html_for('promo.pricing', {'titleField': 'plan'})
        self.assertIn('data__empty', html)


class CompareTests(SimpleTestCase):
    ROWS = [
        {'name': 'Роза', 'cost': 1200, 'weight': 0.4},
        {'name': 'Тюльпан', 'cost': 900, 'weight': 0.3},
        {'name': 'Лилия', 'cost': 1500, 'weight': 0.5},
    ]

    def test_table_with_columns(self):
        html = html_for('shop.compare', {
            'titleField': 'name', 'fields': 'cost\nweight',
            'priceField': 'cost',
        }, self.ROWS)
        self.assertIn('<table class="compare">', html)
        self.assertIn('<th scope="row">Роза</th>', html)
        self.assertIn('<th scope="col">weight</th>', html)

    def test_columns_keep_configured_order(self):
        """Порядок признаков задан настройкой: менять его нельзя."""
        html = html_for('shop.compare', {
            'titleField': 'name', 'fields': 'weight\ncost',
        }, self.ROWS)
        self.assertLess(html.index('>weight<'), html.index('>cost<'))

    def test_price_column_is_formatted(self):
        """Цена форматируется, вес выводится как есть."""
        html = html_for('shop.compare', {
            'titleField': 'name', 'fields': 'cost\nweight',
            'priceField': 'cost',
        }, self.ROWS)
        self.assertIn('1200', html)
        self.assertIn('>0.4<', html)

    def test_limit_truncates(self):
        html = html_for('shop.compare', {
            'titleField': 'name', 'fields': 'cost', 'limit': 2,
        }, self.ROWS)
        self.assertEqual(html.count('<tr><th scope="row">'), 2)
        self.assertNotIn('Лилия', html)

    def test_empty_compare_says_so(self):
        self.assertIn('section--compare', html_for('shop.compare', {}))


class ReviewsTests(SimpleTestCase):
    ROWS = [
        {'who': 'Ирина', 'text': 'Пришло быстро', 'stars': 5},
        {'who': 'Павел', 'text': 'Цветок завял', 'stars': 2},
    ]

    def test_author_and_rating_are_shown(self):
        """Раньше отзыв был строкой без имени и оценки."""
        html = html_for('shop.reviews', {
            'authorField': 'who', 'textField': 'text', 'ratingField': 'stars',
        }, self.ROWS)
        self.assertEqual(html.count('class="review"'), 2)
        self.assertIn('Ирина', html)
        self.assertIn('★★★★★', html)
        self.assertIn('★★', html)

    def test_rating_is_capped(self):
        """Оценка выше пяти — это ошибка данных, а не 12 звёзд."""
        html = html_for('shop.reviews', {
            'textField': 'text', 'ratingField': 'stars',
        }, [{'text': 'Ошибка', 'stars': 12}])
        self.assertEqual(html.count('★'), 5)

    def test_limit_truncates(self):
        html = html_for('shop.reviews', {
            'authorField': 'who', 'textField': 'text', 'limit': 1,
        }, self.ROWS)
        self.assertEqual(html.count('class="review"'), 1)
        self.assertIn('Показано 1', html)


class StockTests(SimpleTestCase):
    def test_sum_and_note(self):
        """Остаток — число на момент публикации, и это написано."""
        html = html_for('shop.stock', {'field': 'qty'}, [
            {'qty': 3}, {'qty': 4},
        ])
        self.assertIn('>7</span>', html)
        self.assertIn('на момент публикации', html)

    def test_low_stock_is_marked(self):
        html = html_for('shop.stock', {
            'field': 'qty', 'lowThreshold': 5, 'label': 'Штук',
        }, [{'qty': 2}])
        self.assertIn('stock--low', html)
        self.assertIn('Штук', html)

    def test_zero_is_not_low(self):
        """Ноль — это «нет в наличии», а не «заканчивается»."""
        html = html_for('shop.stock', {'field': 'qty', 'lowThreshold': 5},
                        [{'qty': 0}])
        self.assertIn('stock--out', html)
        self.assertNotIn('stock--low', html)

    def test_non_numeric_ignored(self):
        html = html_for('shop.stock', {'field': 'qty'}, [{'qty': 'много'}])
        self.assertIn('>0</span>', html)


class OrderTests(SimpleTestCase):
    def test_form_has_named_fields(self):
        html = html_for('shop.order', {
            'heading': 'Заявка', 'fields': 'Имя\nТелефон', 'submitLabel': 'Жду звонка',
        })
        self.assertIn('name="f0"', html)
        self.assertIn('name="f1"', html)
        self.assertIn('Жду звонка', html)

    def test_consent_is_required(self):
        """Без согласия на обработку данных заявку принять нельзя."""
        html = html_for('shop.order', {'policyField': 'consent'})
        self.assertIn('type="checkbox"', html)
        self.assertIn('required', html)

    def test_destination_is_honest(self):
        """Статическая форма не отправляет заявку — и это сказано."""
        html = html_for('shop.order', {})
        self.assertIn('рантайм', html)


class NeedsRuntimeTests(SimpleTestCase):
    """Корзина, оформление и поиск: заглушка и скрытый рабочий блок.

    Раньше они выводились общими функциями и выглядели рабочими: список
    товаров на месте корзины, форма на месте оформления. Нажимать было
    некуда, и это выглядело как ошибка платформы, а не как отсутствие
    сервера (ADR-0005).

    Теперь в статике лежит и заглушка, и разметка настоящего блока.
    Видна заглушка: рабочий блок без сервера наполнять нечем, и пустой
    список товаров читался бы как «магазин пуст».
    """

    MODULES = ('shop.cart', 'shop.checkout', 'shop.search')

    def test_explains_why_module_is_empty(self):
        for module in self.MODULES:
            html = html_for(module, {})
            self.assertIn('section--runtime', html, module)
            self.assertIn('rt-placeholder', html, module)
            self.assertIn('рантайм', html, module)

    def test_working_block_is_hidden_without_runtime(self):
        """Клиент открывает его только после ответа сервера."""
        for module in self.MODULES:
            html = html_for(module, {})
            self.assertIn('hidden', html, module)

    def test_block_is_found_by_client(self):
        for module, kind in (('shop.cart', 'cart'), ('shop.checkout', 'checkout'),
                             ('shop.search', 'search')):
            html = html_for(module, {})
            self.assertIn(f'data-runtime="{kind}"', html, module)

    def test_module_name_is_shown(self):
        self.assertIn('Корзина', html_for('shop.cart', {}))
        self.assertIn('Оформление', html_for('shop.checkout', {}))
        self.assertIn('Поиск', html_for('shop.search', {}))

    def test_records_do_not_matter(self):
        """Даже с записями источника блок остаётся заглушкой."""
        html = render_block(block_for('shop.cart', {'source': 'src-1'}), [], [
            {'name': 'Роза', 'cost': 1200},
        ]).html
        self.assertIn('rt-placeholder', html)
        self.assertNotIn('Роза', html)

    def test_consent_is_in_checkout_markup(self):
        """Согласие есть в разметке: без него сервер всё равно откажет,
        но человек не должен узнавать об этом только после отправки."""
        html = html_for('shop.checkout', {})
        self.assertIn('name="consent"', html)
        self.assertIn('type="checkbox"', html)
