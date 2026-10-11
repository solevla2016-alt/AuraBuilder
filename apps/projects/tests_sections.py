"""Пять секций этапа 5: аккордеон, вкладки, галерея, таймлайн, шаги.

Проверяется главное: свойства, заданные в редакторе, доходят до
выгрузки. До правки здесь читались другие имена свойств, чем в схеме
docs/MODULE-PROPS.md, поэтому настроенный аккордеон или таймлайн
выгружался с вопросом по умолчанию — и это было видно только на
готовом сайте.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from projects.export import render_block


def html_of(module: str, props: dict) -> str:
    """Строка разметки блока.

    render_block возвращает RenderedBlock: у него есть .html, а сам он
    не является строкой. Раньше тест клал результат прямо в assertIn
    и получал «argument of type 'RenderedBlock' is not iterable».
    """
    return render_block(block(module, props)).html


def block(module: str, props: dict) -> dict:
    return {
        'id': 'b1',
        'module': module,
        'x': 0,
        'y': 0,
        'width': 640,
        'height': 320,
        'label': module,
        'props': props,
    }


class AccordionTests(SimpleTestCase):
    def test_items_come_from_props(self):
        html = html_of('section.accordion', {
            'heading': 'Поддержка',
            'items': 'Как вернуть заказ?\nСколько идёт доставка?',
})
        self.assertIn('Как вернуть заказ?', html)
        self.assertIn('Сколько идёт доставка?', html)
        self.assertIn('Поддержка', html)

    def test_first_item_is_open_by_default(self):
        html = html_of('section.accordion', {'items': 'Первый\nВторой'})
        self.assertEqual(html.count('<details open'), 1)

    def test_first_open_can_be_turned_off(self):
        html = html_of('section.accordion', {
            'items': 'Первый\nВторой',
            'firstOpen': False,
})
        self.assertEqual(html.count('<details open'), 0)

    def test_answer_after_colon_becomes_body(self):
        html = html_of('section.accordion', {
            'items': 'Как вернуть: в течение 30 дней',
})
        self.assertIn('<summary>Как вернуть</summary>', html)
        self.assertIn('в течение 30 дней', html)

    def test_heading_falls_back_to_block_label(self):
        """Подпись блока используется как заголовок секции.

        Так работает _text для всех модулей: в панели поле называется
        «Название» и попадает в label.
        """
        html = html_of('section.accordion', {'items': 'Первый'})
        self.assertIn('<h2>section.accordion</h2>', html)

    def test_empty_items_fall_back_without_crashing(self):
        """Пустой список не должен ронять выгрузку.

        Пустая секция выглядит как ошибка сборки, хотя собрана верно,
        поэтому подставляются значения по умолчанию.
        """
        html = html_of('section.accordion', {})
        self.assertIn('<details', html)
        self.assertTrue(html.strip().endswith('</section>'))


class TabsTests(SimpleTestCase):
    def test_tabs_come_from_props(self):
        html = html_of('section.tabs', {
            'tabs': 'Самовывоз\nКурьер\nПочта',
})
        for label in ('Самовывоз', 'Курьер', 'Почта'):
            self.assertIn(label, html)

    def test_columns_limit_trims_tabs(self):
        html = html_of('section.tabs', {
            'tabs': 'Один\nДва\nТри\nЧетыре',
            'columns': 2,
})
        self.assertIn('Один', html)
        self.assertIn('Два', html)
        self.assertNotIn('Четыре', html)

    def test_no_scripts_in_output(self):
        """Пакет должен работать без платформы, а значит без JS."""
        html = html_of('section.tabs', {'tabs': 'Один\nДва'})
        self.assertNotIn('<script', html)


class GalleryTests(SimpleTestCase):
    def test_columns_and_gap_reach_markup(self):
        """Свойства раскладки должны доходить до CSS-переменных.

        Раньше читалось count — свойства, которого в схеме нет,
        поэтому настройки колонок и промежутка в выгрузку не попадали.
        """
        html = html_of('section.gallery', {
            'columns': 4,
            'gap': 24,
})
        self.assertIn('--gallery-columns:4', html)
        self.assertIn('--gallery-gap:24px', html)

    def test_out_of_range_values_are_clamped(self):
        html = html_of('section.gallery', {'columns': 99, 'gap': 9999})
        self.assertIn('--gallery-columns:3', html)
        self.assertIn('--gallery-gap:16px', html)

    def test_heading_is_rendered(self):
        html = html_of('section.gallery', {'heading': 'Портфолио'})
        self.assertIn('Портфолио', html)


class TimelineTests(SimpleTestCase):
    def test_years_follow_start_and_step(self):
        html = html_of('section.timeline', {
            'year': 2020,
            'stepYears': 3,
            'events': 3,
})
        self.assertIn('2020', html)
        self.assertIn('2023', html)
        self.assertIn('2026', html)
        self.assertNotIn('2029', html)

    def test_event_labels_come_from_props(self):
        html = html_of('section.timeline', {
            'year': 2024,
            'stepYears': 1,
            'events': 2,
            'event0': 'Первый запуск',
            'event1': 'Первый клиент',
})
        self.assertIn('Первый запуск', html)
        self.assertIn('Первый клиент', html)

    def test_events_out_of_range_falls_back_to_default(self):
        """Значение вне диапазона заменяется значением по умолчанию.

        Не обрезается до 8 и не печатается как есть: молчаливое
        округление выглядело бы так, будто выбрано 500 событий.
        """
        html = html_of('section.timeline', {'events': 500})
        self.assertEqual(html.count('timeline__item'), 4)


class StepsTests(SimpleTestCase):
    def test_steps_come_from_props(self):
        html = html_of('section.steps', {
            'steps': 'Оставили заявку\nСогласовали\nПолучили',
})
        for label in ('Оставили заявку', 'Согласовали', 'Получили'):
            self.assertIn(label, html)

    def test_numbers_can_be_turned_off(self):
        html = html_of('section.steps', {
            'steps': 'Раз\nДва',
            'showNumbers': False,
})
        self.assertNotIn('steps__num', html)

    def test_numbers_shown_by_default(self):
        html = html_of('section.steps', {'steps': 'Раз\nДва'})
        self.assertEqual(html.count('steps__num'), 2)
