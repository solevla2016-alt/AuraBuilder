"""Юридические и доверительные модули этапа 5.

Проверяется то, что потерялось незаметно: до правки выгрузка
подставляла «Текст оферты» и «Наименование, ИНН, ОГРН, адрес»
независимо от того, что введено в редакторе. Для юридического
документа это означало, что на сайте заказчика оказывался чужой
текст, выглядящий настоящим.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from projects.export import render_block


def html_of(module: str, props: dict) -> str:
    return render_block({
        'id': 'b1',
        'module': module,
        'x': 0,
        'y': 0,
        'width': 640,
        'height': 320,
        'label': 'Блок',
        'props': props,
    }).html


class LegalDocumentTests(SimpleTestCase):
    """Оферта и политика конфиденциальности."""

    def test_offer_text_reaches_output(self):
        html = html_of('legal.offer', {
            'heading': 'Публичная оферта',
            'body': 'Продавец обязуется передать товар.',
        })
        self.assertIn('Продавец обязуется передать товар.', html)
        self.assertNotIn('Текст оферты.', html)

    def test_policy_text_reaches_output(self):
        html = html_of('legal.policy', {
            'body': 'Персональные данные обрабатываются в целях исполнения договора.',
        })
        self.assertIn('Персональные данные обрабатываются', html)
        self.assertNotIn('Текст политики.', html)

    def test_paragraphs_are_kept_separate(self):
        """Переводы строк сохраняются.

        Абзацы слиплись бы в один параграф, и документ стал бы
        нечитаемым — ради читаемости он и выводится текстом.
        """
        html = html_of('legal.offer', {'body': 'Первый абзац\nВторой абзац'})
        self.assertEqual(html.count('<p>'), 2)

    def test_revision_date_is_shown(self):
        html = html_of('legal.offer', {'body': 'Текст', 'updated': '01.10.2026'})
        self.assertIn('Редакция от 01.10.2026', html)

    def test_placeholder_says_it_must_be_filled(self):
        """Пустой документ должен говорить, что его надо заполнить.

        Раньше выводилось «Текст оферты.» — это выглядит как
        готовый документ, и заказчик мог опубликовать его как есть.
        """
        html = html_of('legal.offer', {})
        self.assertIn('не заполнен', html)
        self.assertIn('Заполните', html)

    def test_ids_differ_so_anchor_works(self):
        offer = html_of('legal.offer', {'body': 'Текст'})
        policy = html_of('legal.policy', {'body': 'Текст'})
        self.assertIn('id="offer"', offer)
        self.assertIn('id="policy"', policy)


class RequisitesTests(SimpleTestCase):
    def test_fields_are_rendered(self):
        html = html_of('legal.requisites', {
            'name': 'ООО «Ромашка»',
            'inn': '7701234567',
            'ogrn': '1157746000000',
            'address': 'Москва, ул. Тверская, 1',
            'email': 'hello@example.com',
        })
        self.assertIn('ООО «Ромашка»', html)
        self.assertIn('7701234567', html)
        self.assertIn('1157746000000', html)
        self.assertIn('Москва, ул. Тверская, 1', html)
        self.assertIn('hello@example.com', html)

    def test_fields_are_labeled(self):
        """ИНН и ОГРН проверяют при закупке: без подписи их не найти."""
        html = html_of('legal.requisites', {'inn': '7701234567', 'ogrn': '1157746000000'})
        self.assertIn('ИНН', html)
        self.assertIn('ОГРН', html)

    def test_absent_field_is_not_rendered_as_dash(self):
        html = html_of('legal.requisites', {'name': 'ООО «Ромашка»', 'inn': '7701234567'})
        self.assertNotIn('ОГРН', html)
        self.assertNotIn('—', html)


class ReviewTests(SimpleTestCase):
    def test_author_and_text_come_from_props(self):
        """Раньше поля читались из одного свойства через «|».

        Схемы таких свойств нет: author, rating и text настраиваются
        по отдельности, и в выгрузку не попадали.
        """
        html = html_of('trust.review', {
            'author': 'Мария',
            'rating': 4,
            'text': 'Привезли быстро.',
        })
        self.assertIn('Мария', html)
        self.assertIn('Привезли быстро.', html)
        self.assertEqual(html.count('★'), 4)

    def test_rating_is_clamped(self):
        html = html_of('trust.review', {'author': 'A', 'text': 'B', 'rating': 99})
        self.assertEqual(html.count('★'), 5)


class RatingTests(SimpleTestCase):
    def test_value_and_count_come_from_props(self):
        html = html_of('trust.rating', {'value': 4.6, 'count': 87})
        self.assertIn('4.6', html)
        self.assertIn('87', html)

    def test_fractional_value_is_not_dropped(self):
        """Значение 4.8 — обычное, и int('4.8') его терял бы."""
        html = html_of('trust.rating', {'value': 4.8, 'count': 10})
        self.assertIn('4.8', html)

    def test_source_is_shown_when_set(self):
        html = html_of('trust.rating', {'value': 4.9, 'count': 10, 'source': 'Яндекс'})
        self.assertIn('Яндекс', html)


class LogosTests(SimpleTestCase):
    def test_items_come_from_props(self):
        html = html_of('trust.logos', {'items': 'Альфа;Бета;Гамма'})
        for name in ('Альфа', 'Бета', 'Гамма'):
            self.assertIn(name, html)

    def test_heading_is_rendered(self):
        html = html_of('trust.logos', {'heading': 'С нами работают', 'items': 'Альфа'})
        self.assertIn('С нами работают', html)

    def test_semicolon_default_is_split(self):
        """Значение по умолчанию из схемы записано через «;».

        Перевода строки в одном поле схемы не бывает, поэтому список
        по умолчанию пришёл бы одним словом.
        """
        html = html_of('trust.logos', {})
        self.assertEqual(html.count('logos__item'), 3)


class ConsentTests(SimpleTestCase):
    def test_checkbox_is_required_by_default(self):
        """Без согласия форма отправляет данные без правового основания."""
        html = html_of('legal.consent', {'text': 'Я согласен', 'link': '/privacy-policy'})
        self.assertIn('required', html)
        self.assertIn('/privacy-policy', html)

    def test_text_comes_from_props(self):
        html = html_of('legal.consent', {'text': 'Согласен на рассылку'})
        self.assertIn('Согласен на рассылку', html)


class MarksTests(SimpleTestCase):
    def test_age_mark_is_framed_and_labelled(self):
        """Маркировка должна читаться явно, а не быть текстом в потоке.

        Проверяется не конкретный тег: рамка задаётся стилем, а для
        скринридера важна роль элемента с надписью.
        """
        html = html_of('legal.age-mark', {'text': '18+', 'note': 'Для взрослых'})
        self.assertIn('18+', html)
        self.assertIn('Для взрослых', html)
        self.assertIn('age-mark__sign', html)
        self.assertIn('role="img"', html)
        self.assertIn('aria-label="18+"', html)

    def test_age_mark_has_note_slot(self):
        """Пояснение выводится, только если оно задано."""
        without = html_of('legal.age-mark', {'text': '18+'})
        self.assertNotIn('<small>', without)

    def test_ad_mark_shows_label_with_link(self):
        html = html_of('legal.ad-mark', {
            'text': 'Реклама',
            'href': '/ad-info',
            'label': 'Сведения о рекламе',
        })
        self.assertIn('Реклама', html)
        self.assertIn('/ad-info', html)
        self.assertIn('Сведения о рекламе', html)

    def test_ad_mark_without_link_still_marks(self):
        html = html_of('legal.ad-mark', {'text': 'Реклама'})
        self.assertIn('Реклама', html)
        self.assertNotIn('<a ', html)