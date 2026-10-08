"""Покрытие экспортом всех 65 модулей реестра (ТЗ п.16.4).

Проверяется не «у каждого модуля есть функция», а то, что каждый даёт
пригодный HTML и не ломает страницу. Функция в словаре может вернуть
пустую строку или невалидную разметку — и экспорт это пропустит.
"""

import re

from django.test import SimpleTestCase

from projects.export import RENDERERS, ExportError, render_block
from projects.module_registry import MODULES

#: Модули с особыми требованиями к разметке.
#:
#: Значение — что обязано быть в HTML блока. Пустая строка означает
#: «только непустой результат без внешних ссылок».
EXPECTED: dict[str, str] = {
    'section.hero': '<section',
    'section.header': '<section',
    'section.footer': '<section',
    'section.spacer': 'block--spacer',
    'section.cards': 'class="card"',
    'section.split': 'class="split"',
    'section.cta': '<a class="button"',
    'section.accordion': '<details',
    'section.tabs': '<details',
    'section.gallery': 'gallery__item',
    'section.timeline': '<ol class="timeline"',
    'section.steps': '<ol class="steps"',
    'text.heading': '<h',
    'text.paragraph': '<p',
    'text.list': '<li>',
    'text.quote': '<blockquote',
    'text.code': '<pre',
    'text.table': '<table',
    'media.image': 'role="img"',
    'media.video': 'role="img"',
    'media.audio': '<figcaption',
    'media.file': 'download',
    'media.embed': 'class="embed"',
    'action.button': '<a class="button"',
    'action.link': '<a class="button"',
    'action.form': '<form',
    'data.collection': 'section--data',
    'data.single': 'section--data',
    'data.field': 'data__field',
    'data.list': 'section--data',
    'data.search': 'section--data',
    'data.count': 'data__count',
    'data.pagination': 'section--data',
    'data.aggregate': 'aggregate__value',
    'data.sort': 'section--data',
    'data.filter': 'data__filter-note',
    'data.related': 'section--data',
    'data.form': '<form',
    'nav.breadcrumb': '<ol>',
    'nav.anchor': '<a id=',
    'social.links': '<a href=',
    'seo.schema': 'application/ld+json',
    'legal.age-mark': 'age-mark',
    'legal.ad-mark': 'ad-mark',
    'legal.consent': 'type="checkbox"',
    'legal.offer': 'section--legal',
    'legal.policy': 'section--legal',
    'legal.requisites': 'section--legal',
    'trust.review': '<blockquote',
    'trust.rating': 'rating',
    'trust.logos': 'logos__item',
    'shop.catalog': 'section--data',
    'shop.card': 'section--data',
    'shop.cart': 'section--data',
    'shop.reviews': 'class="reviews"',
    'shop.price': 'class="price',
    'shop.order': '<form',
    'shop.checkout': '<form',
    'shop.search': '<form',
    'shop.stock': 'data__count',
    'shop.compare': '<table',
    'promo.banner': '<section',
    'promo.pricing': 'section--data',
    'code.custom': '<pre',
}


#: Модули, которые без записей источника показывают заглушку, а с
#: записями — разметку. Проверяются с непустым набором, иначе тест
#: требовал бы заглушки там, где её быть не должно.
NEEDS_RECORDS = {
    'data.collection', 'data.list', 'data.single', 'data.search',
    'data.pagination', 'data.field', 'data.count', 'data.aggregate',
    'data.sort', 'data.filter', 'data.related', 'data.form',
    'shop.card', 'shop.catalog', 'shop.cart', 'shop.reviews',
    'shop.price', 'shop.stock', 'shop.compare', 'promo.pricing',
}


#: Модули, которые по смыслу ничего не выводят: отступ и заглушки.
NO_TEXT = {'section.spacer', 'media.embed'}


def block_for(module_id: str, **extra) -> dict:
    return {
        'id': 'b1',
        'module': module_id,
        'x': 0,
        'y': 0,
        'width': 400,
        'height': 120,
        'label': 'Блок',
        'content': 'Текст',
        **extra,
    }


class AllModulesRenderedTests(SimpleTestCase):
    """Каждый модуль реестра обязан иметь рендерер."""

    def test_registry_fully_covered(self):
        missing = [m.id for m in MODULES if m.id not in RENDERERS]
        self.assertEqual(missing, [], f'модули без рендерера: {missing}')

    def test_no_stale_renderers(self):
        # Рендерер для несуществующего модуля — мёртвый код: он никогда
        # не выполнится, но будет выглядеть как рабочая вёрстка.
        known = {m.id for m in MODULES}
        stale = [key for key in RENDERERS if key not in known]
        self.assertEqual(stale, [], f'рендереры без модуля: {stale}')


class ModuleOutputTests(SimpleTestCase):
    """Вывод каждого модуля должен быть пригодной разметкой."""

    def test_every_module_renders_expected_markup(self):
        for module in MODULES:
            with self.subTest(module=module.id):
                records = ['Роза · 1200'] if module.id in NEEDS_RECORDS else None
                rendered = render_block(block_for(module.id), records)
                expected = EXPECTED.get(module.id, '')
                if expected:
                    self.assertIn(
                        expected, rendered.html, f'{module.id}: нет {expected!r}'
                    )
                else:
                    self.assertTrue(rendered.html.strip(), f'{module.id}: пустой вывод')

    def test_no_external_links_in_any_module(self):
        # Проверяется по всему набору: одна ссылка в одном модуле
        # сделала бы пакет зависимым от чужого сервера (п.15.3).
        for module in MODULES:
            with self.subTest(module=module.id):
                html = render_block(block_for(module.id)).html
                for host in ('http://', 'https://', 'fonts.g'):
                    self.assertNotIn(host, html, f'{module.id}: внешняя ссылка')

    def test_markup_is_balanced(self):
        # Незакрытый тег ломает страницу целиком: браузер дорисует
        # остальное сам и утащит чужой блок в футер.
        void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                'link', 'meta', 'param', 'source', 'track', 'wbr'}
        for module in MODULES:
            with self.subTest(module=module.id):
                html = render_block(block_for(module.id)).html
                opened = re.findall(r'<([a-z][a-z0-9]*)(?:\s[^>]*)?>', html)
                closed = re.findall(r'</([a-z][a-z0-9]*)>', html)
                stack = []
                for tag in re.findall(r'<(/?)([a-z][a-z0-9]*)(?:\s[^>]*)?>', html):
                    if tag[1] in void:
                        continue
                    if tag[0] == '/':
                        if not stack or stack[-1] != tag[1]:
                            self.fail(f'{module.id}: тег {tag[1]} закрыт без открытия')
                        stack.pop()
                    else:
                        stack.append(tag[1])
                self.assertEqual(stack, [], f'{module.id}: не закрыты {stack}')

    def test_text_is_escaped_in_every_module(self):
        # Проверяется по всему набору модулей, потому что текст попадает
        # в HTML разными путями: в заголовок, в абзац, в подпись кнопки,
        # в атрибут href. Один незакрытый путь — и это XSS на сайте
        # заказчика.
        #
        # Модули без текста (отступ, разделитель) исключены: они по
        # определению ничего не выводят, и требовать от них экранирования
        # бессмысленно. Для media.embed код выводится как есть — это
        # осознанный риск, о нём сказано в рендерере.
        payload = '<img src=x onerror=alert(1)>'
        for module in MODULES:
            if module.id in NO_TEXT or module.id == 'media.embed':
                continue
            with self.subTest(module=module.id):
                records = ['Роза'] if module.id in NEEDS_RECORDS else None
                rendered = render_block(
                    block_for(module.id, content=payload, label=payload), records
                )
                # После экранирования спецсимволы стоят как текст, а
                # не как разметка. Искать подстроку «onerror=» нельзя:
                # экранирование не удаляет символы, а прячет спецсимволы.
                self.assertNotIn('<img', rendered.html, module.id)

    def test_empty_project_block_does_not_crash(self):
        # Пустой блок без содержимого: редактор такое создаёт, и падать
        # на экспорте из-за этого нельзя.
        for module in MODULES:
            with self.subTest(module=module.id):
                rendered = render_block(
                    {
                        'id': 'b1',
                        'module': module.id,
                        'x': 0,
                        'y': 0,
                        'width': 100,
                        'height': 50,
                        'label': '',
                    }
                )
                self.assertIsInstance(rendered.html, str)


class DataModuleTests(SimpleTestCase):
    """Модули данных получают записи источника."""

    def test_records_are_shown(self):
        rendered = render_block(
            block_for('data.collection'), ['Роза \· 1200', 'Тюльпан \· 900']
        )
        self.assertIn('Роза', rendered.html)
        self.assertIn('Тюльпан', rendered.html)

    def test_empty_source_is_honest(self):
        # Пустой источник не заменяется выдуманными строками.
        rendered = render_block(block_for('data.collection'), [])
        self.assertIn('Нет записей', rendered.html)

    def test_aggregate_sums_numbers(self):
        rendered = render_block(
            block_for('data.aggregate'), ['Роза \· 1200', 'Тюльпан \· 900']
        )
        self.assertIn('2100', rendered.html.replace(' ', ''))

    def test_count_reports_records(self):
        rendered = render_block(block_for('data.count'), ['a', 'b', 'c'])
        self.assertIn('>3<', rendered.html)

    def test_data_form_says_backend_needed(self):
        # Форма без рантайма не должна делать вид, что отправка работает.
        rendered = render_block(block_for('data.form'), [])
        self.assertIn('после подключения бэкенда', rendered.html)


class ErrorTests(SimpleTestCase):
    def test_unknown_module_raises(self):
        with self.assertRaises(ExportError):
            render_block(block_for('section.does-not-exist'))