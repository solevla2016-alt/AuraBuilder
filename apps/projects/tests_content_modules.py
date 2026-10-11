"""Контентные модули этапа 5: аудио, код, соцсети, таблица, файл, якорь.

Проверяется то, что потерялось незаметно: код и таблица читались из
внутреннего поля content, которого нет в панели свойств, поэтому
заполнить их из редактора было нельзя — модуль выводился пустым.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from projects.export import render_block


def html_of(module: str, props: dict | None = None) -> str:
    return render_block({
        'id': 'b1',
        'module': module,
        'x': 0,
        'y': 0,
        'width': 640,
        'height': 320,
        'label': 'Блок',
        'props': props or {},
    }).html


class CodeTests(SimpleTestCase):
    def test_code_comes_from_props(self):
        html = html_of('text.code', {'code': 'print("привет")'})
        self.assertIn('print(&quot;привет&quot;)', html)

    def test_code_is_escaped(self):
        html = html_of('text.code', {'code': '<script>alert(1)</script>'})
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_language_is_marked(self):
        """Язык нужен для подсветки на странице."""
        html = html_of('text.code', {'code': '{}', 'language': 'json'})
        self.assertIn('data-language="json"', html)

    def test_heading_is_optional(self):
        with_heading = html_of('text.code', {'heading': 'Скрипт', 'code': 'x'})
        without = html_of('text.code', {'code': 'x'})
        self.assertIn('Скрипт', with_heading)
        self.assertNotIn('<h3>', without)


class TableTests(SimpleTestCase):
    def test_first_row_is_header(self):
        html = html_of('text.table', {'rows': 'Услуга;Цена\nАудит;30000'})
        self.assertIn('<th scope="col">Услуга</th>', html)
        self.assertIn('<td>Аудит</td>', html)

    def test_semicolon_separator(self):
        # Считаются именно ячейки: '<th' входит в '<thead', и такой
        # подсчёт завышал число столбцов на один.
        html = html_of('text.table', {'rows': 'A;B;C\n1;2;3'})
        self.assertEqual(html.count('scope="col"'), 3)
        self.assertEqual(html.count('<td>'), 3)

    def test_missing_cells_are_padded(self):
        """Без дополнения строка разъезжается и таблица выглядит битой."""
        html = html_of('text.table', {'rows': 'A;B;C\n1;2'})
        self.assertEqual(html.count('<td'), 3)

    def test_empty_table_keeps_structure(self):
        """Место под таблицу уже отведено — исчезать ей некуда."""
        html = html_of('text.table', {})
        self.assertIn('<table', html)
        self.assertIn('Таблица пуста', html)

    def test_multiline_rows(self):
        html = html_of('text.table', {'rows': 'A;B\n1;2\n3;4'})
        self.assertEqual(html.count('<tr>'), 3)


class SocialTests(SimpleTestCase):
    def test_links_are_rendered(self):
        html = html_of('social.links', {'links': 'https://example.com/a\nhttps://example.com/b'})
        self.assertEqual(html.count('<a href'), 2)

    def test_no_external_service_in_default(self):
        """Значение по умолчанию — пример из документации."""
        html = html_of('social.links', {})
        self.assertIn('example.com', html)
        self.assertNotIn('vk.com', html)
        self.assertNotIn('facebook', html)

    def test_heading_is_optional(self):
        self.assertNotIn('<h2>', html_of('social.links', {}))
        self.assertIn('Мы здесь', html_of('social.links', {'heading': 'Мы здесь'}))


class AudioTests(SimpleTestCase):
    def test_no_player_without_source(self):
        """Без файла плеер был бы битым — выводится подпись."""
        html = html_of('media.audio', {'title': 'Подкаст'})
        self.assertIn('Подкаст', html)
        self.assertNotIn('<audio', html)
        self.assertIn('не подключён', html)

    def test_player_appears_with_source(self):
        html = html_of('media.audio', {'title': 'Подкаст', 'src': '/audio/1.mp3'})
        self.assertIn('<audio', html)
        self.assertIn('/audio/1.mp3', html)

    def test_flags_are_off_by_default(self):
        html = html_of('media.audio', {'src': '/a.mp3'})
        self.assertNotIn('autoplay', html)
        self.assertNotIn(' loop', html)

    def test_flags_can_be_turned_on(self):
        html = html_of('media.audio', {'src': '/a.mp3', 'autoplay': True, 'loop': True})
        self.assertIn('autoplay', html)
        self.assertIn('loop', html)


class FileTests(SimpleTestCase):
    def test_no_link_without_address(self):
        """Ссылка в никуда хуже, чем подпись."""
        html = html_of('media.file', {'title': 'Прайс'})
        self.assertNotIn('<a ', html)
        self.assertIn('Прайс', html)
        self.assertIn('не прикреплён', html)

    def test_link_appears_with_address(self):
        html = html_of('media.file', {'title': 'Прайс', 'href': '/price.pdf'})
        self.assertIn('download', html)
        self.assertIn('/price.pdf', html)

    def test_size_is_shown(self):
        html = html_of('media.file', {'title': 'Прайс', 'href': '/p.pdf', 'size': '2,4 МБ'})
        self.assertIn('2,4 МБ', html)


class AnchorTests(SimpleTestCase):
    def test_anchor_uses_property(self):
        html = html_of('nav.anchor', {'anchor': 'contacts'})
        self.assertIn('id="contacts"', html)

    def test_falls_back_to_block_id(self):
        html = html_of('nav.anchor', {})
        self.assertIn('id="b1"', html)

    def test_label_is_optional(self):
        self.assertNotIn('visually-hidden', html_of('nav.anchor', {}))
        self.assertIn('visually-hidden', html_of('nav.anchor', {'label': 'Контакты'}))