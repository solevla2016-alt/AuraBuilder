"""Экспорт проекта в статический пакет (ТЗ п.16.4).

Задача модуля — превратить снимок версии документа в архив, который
открывается без платформы. Пользователь получает результат, а не
инструмент: редактор, рантайм платформы и учётные данные интеграций в
пакет не попадают (п.16.4, ограничение IP Safety).

Что здесь и почему не больше:

* Снимок версии. Экспорт идёт по номеру версии, а не по текущему
  состоянию: повторный экспорт той же версии обязан дать тот же
  результат (ТЗ п.16.2), иначе сборку нельзя сравнивать и нельзя
  переделывать при сбое.

* Рендер дерева в HTML. Прямо в строку, без шаблонного движка: пакет
  должен быть читаемым и проверяемым, а Jinja в архиве ничего не
  объясняет.

* Стили собираются из палитры проекта. Файл один — сторонних ссылок в
  пакете быть не должно (п.16.4, п.15.3), а @import и внешние шрифты
  делали бы сайт зависимым от чужого сервера.

* Частичного экспорта нет. Если хоть один модуль не удалось отрисовать,
  весь пакет считается неуспешным (п.16.2): отдать половину значило бы
  отдать сайт, который выглядит рабочим и молча теряет блоки.
"""

from __future__ import annotations

import hashlib
import html
import json
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from .module_registry import MODULE_IDS
from .palette_tokens import THEMES

#: Версия формата пакета. Меняется, когда меняется структура каталогов
#: или манифеста: без неё нельзя отличить новый пакет от старого.
FORMAT_VERSION = 1

#: Домены, которые не должны попасть в пакет ни при каких условиях.
#: Перечисление явное, а не эвристическое «ищем http»: правило «никаких
#: внешних ссылок» проверяется по факту, а не по догадке.
FORBIDDEN_HOSTS = (
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    'cdn.cloudflare.net',
    'ajax.googleapis.com',
    'unpkg.com',
    'cdnjs.cloudflare.com',
    'cdn.skypack.dev',
    'jsdelivr.net',
    'google-analytics.com',
    'googletagmanager.com',
)


class ExportError(Exception):
    """Экспорт не удался. Пакет в этом случае не выдаётся."""


@dataclass
class RenderedBlock:
    """Один блок, готовый к вставке в HTML."""

    block_id: str
    module_id: str
    html: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    """Готовый пакет и сведения о сборке."""

    filename: str
    content: bytes
    manifest: dict[str, Any]
    warnings: list[str]


def esc(value: Any) -> str:
    """Экранирование текста для HTML.

    Собирается вручную, а не через django.utils.html.escape: модуль
    работает вне Django (тесты конвейера запускаются без настройки
    проекта), а пропущенное экранирование — это XSS на сайте заказчика.
    """

    text = '' if value is None else str(value)
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )


def slugify(value: str) -> str:
    """Имя файла или каталога из заголовка.

    Кириллица сохраняется: адрес вида «розы-и-букеты.html» читается и
    работает без сервера. Раньше не-ASCII буквы считались разделителями,
    и русский заголовок давал пустой slug — то есть файл назывался
    page.html вместо осмысленного имени.
    """

    out: list[str] = []
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append('-')
    slug = ''.join(out)
    while '--' in slug:
        slug = slug.replace('--', '-')
    return slug.strip('-') or 'page'


def _props(block: dict) -> dict[str, Any]:
    value = block.get('props')
    return value if isinstance(value, dict) else {}


def _text(block: dict, name: str, fallback: str = '') -> str:
    """Текст блока: свойство, затем содержимое, затем подпись.

    Порядок важен для одинакового результата в редакторе и пакете:
    в панели свойств поле называется «Название» и попадает в label,
    а в модуле этому же полю соответствует props.text. Пока приоритет
    у props, подпись из label подставлялась только пустым текстом — и
    правка названия блока не доезжала до выгрузки.
    """

    value = _props(block).get(name)
    if isinstance(value, str) and value.strip():
        return value
    content = block.get('content')
    if isinstance(content, str) and content.strip():
        return content
    label = block.get('label')
    if isinstance(label, str) and label.strip():
        return label
    return fallback


def _align(block: dict) -> str:
    align = block.get('align')
    return align if align in ('left', 'center', 'right') else 'left'


def _render_heading(block: dict, level: int = 2) -> str:
    tag = f'h{min(max(level, 1), 6)}'
    return f'<{tag} class="block block--text" style="text-align:{_align(block)}">{esc(_text(block, "text", "Заголовок"))}</{tag}>'


def _render_paragraph(block: dict) -> str:
    return (
        '<p class="block block--text" '
        f'style="text-align:{_align(block)}">{esc(_text(block, "text", "Текст абзаца."))}</p>'
    )


def _render_list(block: dict) -> str:
    items = [
        line.strip()
        for line in str(block.get('content') or '').splitlines()
        if line.strip()
    ] or ['Первый пункт', 'Второй пункт']
    entries = ''.join(f'<li>{esc(item)}</li>' for item in items)
    return f'<ul class="block block--text">{entries}</ul>'


def _render_quote(block: dict) -> str:
    return (
        '<blockquote class="block block--text">'
        f'{esc(_text(block, "text", "Цитата"))}</blockquote>'
    )


def _render_section(block: dict, records: list[dict] | None = None) -> str:
    """Секция: заголовок, подзаголовок и кнопка, если они заданы.

    У заголовка есть запасной источник — подпись блока. Без него секция
    с ненастроенными свойствами выглядела пустой: заголовок первого
    экрана хранится в панели свойств, а не в содержимо�� блока.
    """

    parts: list[str] = []
    heading = _text(block, 'heading') or _text(block, 'text')
    if heading:
        parts.append(f'<h2 class="section__title">{esc(heading)}</h2>')
    subheading = _text(block, 'subheading')
    if subheading:
        parts.append(f'<p class="section__subtitle">{esc(subheading)}</p>')
    body = block.get('content')
    if isinstance(body, str) and body.strip():
        parts.append(f'<div class="section__body">{esc(body)}</div>')
    button = _text(block, 'buttonLabel')
    link = _text(block, 'buttonLink', '#')
    if button:
        parts.append(
            f'<a class="button" href="{esc(link)}">{esc(button)}</a>'
        )
    inner = '\n'.join(parts)
    return f'<section class="section">\n{inner}\n</section>'


def _render_cards(block: dict, records: list[dict] | None = None) -> str:
    columns = _props(block).get('columns')
    count = columns if isinstance(columns, int) and 2 <= columns <= 4 else 3
    titles = ['Скорость', 'Надёжность', 'Поддержка', 'Понятность']
    cards = ''.join(
        f'<article class="card"><h3>{esc(titles[i % len(titles)])}</h3>'
        '<p>Описание преимущества.</p></article>'
        for i in range(count)
    )
    heading = _text(block, 'heading') or _text(block, 'text')
    title = f'<h2 class="section__title">{esc(heading)}</h2>' if heading else ''
    return (
        f'<section class="section section--cards">{title}'
        f'<div class="cards">{cards}</div></section>'
    )


def _render_split(block: dict, records: list[dict] | None = None) -> str:
    left = _text(block, 'heading') or _text(block, 'text') or 'Левая колонка'
    return (
        '<section class="section section--split"><div class="split">'
        f'<div><h2>{esc(left)}</h2><p>Текст колонки.</p></div>'
        '<div><h2>Правая колонка</h2><p>Текст колонки.</p></div>'
        '</div></section>'
    )


def _render_cta(block: dict, records: list[dict] | None = None) -> str:
    heading = _text(block, 'heading') or _text(block, 'text') or 'Готовы начать?'
    button = _text(block, 'buttonLabel', 'Начать')
    link = _text(block, 'buttonLink', '#')
    return (
        '<section class="section section--cta">'
        f'<h2>{esc(heading)}</h2>'
        f'<a class="button" href="{esc(link)}">{esc(button)}</a>'
        '</section>'
    )


def _render_anchor(block: dict) -> str:
    """Якорь: пустая метка в разметке, к которой ведут ссылки меню."""
    return f'<a id="{esc(_text(block, "anchor", block.get("id", "anchor")))}"></a>'


def _render_breadcrumbs(block: dict) -> str:
    """Хлебные крошки из текста «Главная / Каталог / Розы»."""
    raw = _text(block, 'items') or _text(block, 'text') or 'Главная'
    parts = [p.strip() for p in raw.split('/') if p.strip()] or ['Главная']
    items = ''.join(f'<li>{esc(part)}</li>' for part in parts)
    return f'<nav class="breadcrumbs" aria-label="Хлебные крошки"><ol>{items}</ol></nav>'


def _render_accordion(block: dict) -> str:
    """Аккордеон на нативном <details>."""
    title = _text(block, 'title', 'Вопрос')
    body = _text(block, 'text', 'Ответ')
    return (
        '<details class="block block--accordion">'
        f'<summary>{esc(title)}</summary><p>{esc(body)}</p></details>'
    )


def _render_tabs(block: dict) -> str:
    """Вкладки.

    Разметка семантическая, переключение — CSS через :target или
    checkbox. Скрипт в статическом пакете не нужен: пакет должен
    работать без платформы, а :target работает везде.
    """
    raw = _text(block, 'items', 'Один\nДва\nТри')
    items = [line.strip() for line in raw.split('\n') if line.strip()] or ['Один']
    parts = []
    for i, item in enumerate(items):
        open_attr = ' open' if i == 0 else ''
        parts.append(
            f'<details class="tabs__item"{open_attr}><summary>{esc(item)}</summary>'
            f'<p>{esc(item)}</p></details>'
        )
    return f'<div class="tabs">{"".join(parts)}</div>'


def _render_gallery(block: dict) -> str:
    """Галерея плейсхолдеров: файлов на стенде нет."""
    count = _props(block).get('count')
    count = count if isinstance(count, int) and 2 <= count <= 12 else 3
    cells = ''.join(
        f'<figure class="gallery__item"><div class="media__placeholder" role="img" '
        f'aria-label="Изображение {i + 1}">Изображение {i + 1}</div></figure>'
        for i in range(count)
    )
    return f'<div class="gallery">{cells}</div>'


def _render_timeline(block: dict) -> str:
    raw = _text(block, 'items', '2024\n2025\n2026')
    items = [line.strip() for line in raw.split('\n') if line.strip()] or ['2026']
    entries = ''.join(
        f'<li class="timeline__item"><span>{esc(item)}</span></li>' for item in items
    )
    return f'<ol class="timeline">{entries}</ol>'


def _render_steps(block: dict) -> str:
    raw = _text(block, 'items', 'Шаг 1\nШаг 2\nШаг 3')
    items = [line.strip() for line in raw.split('\n') if line.strip()] or ['Шаг 1']
    entries = ''.join(
        f'<li class="steps__item"><span class="steps__num">{i + 1}</span>'
        f'<span>{esc(item)}</span></li>'
        for i, item in enumerate(items)
    )
    return f'<ol class="steps">{entries}</ol>'


def _render_audio(block: dict) -> str:
    # Аудиофайла нет, и подставлять чужой src нельзя: страница получила
    # бы битый плеер. Показывается подпись с местом под файл.
    title = _text(block, 'title', 'Аудио')
    return (
        '<figure class="block block--audio">'
        f'<figcaption class="media__placeholder">{esc(title)}</figcaption></figure>'
    )


def _render_code(block: dict) -> str:
    return f'<pre class="block block--code"><code>{esc(block.get("content"))}</code></pre>'


def _render_social(block: dict) -> str:
    """Ссылки на соцсети.

    Адреса берутся из текста построчно: список href в настройках
    означал бы, что экспорт должен ходить в сеть за разбором ссылок.
    """
    raw = _text(block, 'links') or _text(block, 'text')
    links = [line.strip() for line in raw.split('\n') if line.strip()]
    items = ''.join(f'<li><a href="{esc(link)}">{esc(link)}</a></li>' for link in links)
    if not items:
        items = '<li>Ссылки появятся после настройки модуля.</li>'
    return f'<ul class="social">{items}</ul>'


def _render_table(block: dict) -> str:
    """Таблица из содержимого: первая строка — заголовки."""
    raw = block.get('content')
    rows = [line for line in str(raw or '').splitlines() if line.strip()]
    if not rows:
        return '<p class="block block--text">Таблица пуста.</p>'
    header = [c.strip() for c in rows[0].split('|') if c.strip()]
    head = ''.join(f'<th scope="col">{esc(c)}</th>' for c in header)
    body = ''
    for line in rows[1:]:
        cells = [c.strip() for c in line.split('|') if c.strip()]
        body += '<tr>' + ''.join(f'<td>{esc(c)}</td>' for c in cells) + '</tr>'
    return (
        f'<table class="block block--table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{body}</tbody></table>'
    )


def _render_file(block: dict) -> str:
    title = _text(block, 'title', 'Файл')
    return (
        '<a class="block block--file" href="#" download>'
        f'{esc(title)}</a>'
    )


def _render_embed(block: dict) -> str:
    """Встраивание.

    Код iframe вставляется как есть: это осознанный риск, он виден
    автору проекта, а платформа ничего не может проверить в чужом
    коде. Плейсхолдер без кода означал бы модуль, который ничего не
    показывает.
    """
    code = _text(block, 'code', _text(block, 'text', ''))
    title = _text(block, 'title', 'Встраивание')
    if not code:
        return (
            '<figure class="block block--media">'
            f'<div class="media__placeholder">{esc(title)}</div></figure>'
        )
    return f'<div class="embed">{code}</div>'


def _render_schema(block: dict) -> str:
    """Микроразметка Schema.org (ТЗ п.8.1).

    Выводится отдельным блоком сценарием JSON-LD, а не в тело страницы:
    поисковики читают именно отсюда, и подмена разметки вручную не
    должна ломать выдачу.
    """
    raw = _text(block, 'json') or _text(block, 'text')
    if not raw:
        return ''
    return (
        '<script type="application/ld+json">'
        f'{esc(raw)}</script>'
    )


def _render_age_mark(block: dict) -> str:
    """Знак возрастной маркировки (ТЗ п.9.2).

    Текст обязателен законом и не должен пропасть при экспорте: без
    него площадка может отклонить публикацию.
    """
    text = _text(block, 'text', _text(block, 'label', '18+'))
    return f'<div class="legal age-mark">{esc(text)}</div>'


def _render_ad_mark(block: dict) -> str:
    label = _text(block, 'label', 'Реклама')
    href = _text(block, 'link', '')
    body = f'<a href="{esc(href)}">{esc(label)}</a>' if href else esc(label)
    return f'<div class="legal ad-mark">{body}</div>'


def _render_consent(block: dict) -> str:
    """Согласие на обработку персональных данных.

    Ссылка обязательна: без неё форма отправляет данные без правового
    основания, и это останавливает публикацию магазина.
    """
    text = _text(block, 'text', 'Я согласен на обработку персональных данных')
    href = _text(block, 'link', '/privacy')
    return (
        '<p class="legal consent">'
        f'<label><input type="checkbox" required> {esc(text)} '
        f'<a href="{esc(href)}">политика</a></label></p>'
    )


def _render_review(block: dict) -> str:
    """Отзыв: оценка, имя, текст."""
    raw = _text(block, 'items') or _text(block, 'text')
    parts = [p.strip() for p in raw.split('|') if p.strip()]
    author = parts[0] if parts else 'Покупатель'
    rating = parts[1] if len(parts) > 1 else '5'
    body = parts[2] if len(parts) > 2 else 'Отзыв покупателя'
    stars = '★' * max(0, min(5, int(rating) if str(rating).isdigit() else 5))
    return (
        '<figure class="review block">'
        f'<blockquote>{esc(body)}</blockquote>'
        f'<figcaption>{stars} · {esc(author)}</figcaption></figure>'
    )


def _render_rating(block: dict) -> str:
    raw = _text(block, 'items') or _text(block, 'text')
    parts = [p.strip() for p in raw.split('|') if p.strip()]
    value = parts[0] if parts else '4.8'
    count = parts[1] if len(parts) > 1 else '120'
    return (
        '<div class="rating block">'
        f'<b>{esc(value)}</b> · {esc(count)} отзывов</div>'
    )


def _render_logos(block: dict) -> str:
    raw = _text(block, 'items') or _text(block, 'text')
    items = [line.strip() for line in raw.split('\n') if line.strip()] or ['Логотип']
    cells = ''.join(
        f'<div class="logos__item media__placeholder">{esc(item)}</div>' for item in items
    )
    return f'<div class="logos">{cells}</div>'


def _render_offer(block: dict) -> str:
    heading = _text(block, 'heading', 'Публичная оферта')
    return (
        '<section class="section section--legal"><h2>'
        f'{esc(heading)}</h2><p>Текст оферты.</p></section>'
    )


def _render_policy(block: dict) -> str:
    heading = _text(block, 'heading', 'Политика конфиденциальности')
    return (
        '<section class="section section--legal"><h2>'
        f'{esc(heading)}</h2><p>Текст политики.</p></section>'
    )


def _render_requisites(block: dict) -> str:
    heading = _text(block, 'heading', 'Реквизиты')
    return (
        '<section class="section section--legal"><h2>'
        f'{esc(heading)}</h2><p>Наименование, ИНН, ОГРН, адрес.</p></section>'
    )


def _render_review_list(block: dict, records: list[dict] | None = None) -> str:
    """Отзывы из источника."""
    rows = records or []
    if not rows:
        return '<section class="section section--data"><p class="data__empty">Нет отзывов</p></section>'
    items = ''.join(
        f'<li class="review"><blockquote>{esc(row)}</blockquote></li>' for row in rows
    )
    return f'<section class="section section--data"><ul class="reviews">{items}</ul></section>'


def _render_table_from_records(block: dict, records: list[dict] | None = None) -> str:
    """Сравнение товаров: значения источника в таблицу."""
    rows = records or []
    if not rows:
        return '<section class="section section--data"><p class="data__empty">Нет товаров</p></section>'
    body = ''
    for row in rows:
        cells = ''.join(f'<td>{esc(part)}</td>' for part in str(row).split(' \u00b7 '))
        body += f'<tr>{cells}</tr>'
    return (
        '<section class="section section--data">'
        f'<table class="block block--table"><tbody>{body}</tbody></table></section>'
    )


def _render_single(block: dict, records: list[dict] | None = None) -> str:
    """Одна запись источника. Пусто — честная заглушка."""
    rows = records or []
    if not rows:
        return (
            '<section class="section section--data">'
            '<p class="data__empty">Нет записей</p></section>'
        )
    return (
        '<section class="section section--data">'
        f'<p class="data__single">{esc(rows[0])}</p></section>'
    )


def _render_field(block: dict, records: list[dict] | None = None) -> str:
    """Одно поле источника: подпись плюс значение первой записи."""
    rows = records or []
    name = _text(block, 'field', _text(block, 'label', 'Поле'))
    value = rows[0] if rows else ''
    return (
        '<section class="section section--data">'
        f'<p class="data__field"><span class="data__field-name">{esc(name)}</span>'
        f'<span class="data__field-value">{esc(value)}</span></p></section>'
    )


def _render_count(block: dict, records: list[dict] | None = None) -> str:
    """Счётчик записей источника."""
    return (
        '<section class="section section--data">'
        f'<p class="data__count">{len(records or [])}</p></section>'
    )


def _render_price(block: dict, records: list[dict] | None = None) -> str:
    """Цена из источника или из свойства блока."""
    rows = records or []
    value = rows[0] if rows else _text(block, 'value', '\u2014')
    return f'<p class="price block">{esc(value)}</p>'


def _render_aggregate(block: dict, records: list[dict] | None = None) -> str:
    """Итог по источнику: сумма чисел, которые в нём нашлись."""
    total = 0.0
    found = False
    for row in records or []:
        for part in str(row).split(' \u00b7 '):
            cleaned = ''.join(c for c in part if c.isdigit() or c in '.,-')
            if not cleaned:
                continue
            try:
                total += float(cleaned.replace(',', '.'))
                found = True
            except ValueError:
                continue
    label = _text(block, 'label', 'Итого')
    value = f'{total:.2f}'.rstrip('0').rstrip('.') if found else '\u2014'
    return (
        f'<p class="aggregate block"><span class="aggregate__label">{esc(label)}</span>'
        f'<span class="aggregate__value">{esc(value)}</span></p>'
    )


def _render_data_sort(block: dict, records: list[dict] | None = None) -> str:
    """Сортировка фиксируется в пакете: рантайма, который её применял бы, нет."""
    return _render_data(block, records)


def _render_data_related(block: dict, records: list[dict] | None = None) -> str:
    """Связанные записи: список без раскрытия связей."""
    return _render_data(block, records)


def _render_data_filter(block: dict, records: list[dict] | None = None) -> str:
    """Фильтр статичен.

    Без рантайма фильтровать нечем, поэтому показывается весь набор и
    прямая подпись о том, что фильтр заработает с бэкендом. Рисовать
    «отфильтрованный» вид значило бы соврать о данных.
    """
    items = ''.join(f'<li>{esc(row)}</li>' for row in records or [])
    body = f'<ul class="data">{items}</ul>' if items else '<p class="data__empty">Нет записей</p>'
    return (
        '<section class="section section--data">'
        '<p class="data__filter-note">Фильтр применится после подключения бэкенда.</p>'
        f'{body}</section>'
    )


def _render_data_form(block: dict, records: list[dict] | None = None) -> str:
    """Форма записи из узла данных.

    Обработчика нет: отправлять значения некуда, поэтому форма только
    собирает их, а подпись говорит об этом прямо.
    """
    fields = _props(block).get('fields')
    names: list[str] = []
    if isinstance(fields, list):
        for item in fields:
            if isinstance(item, dict):
                names.append(str(item.get('label') or item.get('name') or 'Поле'))
    rows = records or []
    names = names or (rows[0].split(' \u00b7 ') if rows else ['Значение'])
    inputs = ''.join(
        f'<label class="field">{esc(name)}<input name="f{index}" '
        f'data-source-field="{esc(index)}"></label>'
        for index, name in enumerate(names)
    )
    return (
        '<section class="section section--data"><h2>'
        f'{esc(_text(block, "label", "Форма"))}</h2>'
        f'<form class="form" method="post">{inputs}</form>'
        '<p class="data__note">Отправка заработает после подключения бэкенда.</p>'
        '</section>'
    )


def _render_form(block: dict, records: list[dict] | None = None) -> str:
    """Форма в статическом пакете.

    Обработчика здесь быть не может: логика живёт на платформе, а пакет
    без неё автономен (п.16.4). Поэтому выводится только разметка с
    честной подписью — иначе посетитель отправил бы данные в никуда.
    """

    title = _text(block, 'title', _text(block, 'label', 'Форма'))
    action = _text(block, 'action', '')
    method = _text(block, 'method', 'post').lower()
    method = method if method in ('post', 'get') else 'post'
    fields = []
    raw = _props(block).get('fields')
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or item.get('label') or 'field')
            kind = str(item.get('type') or 'text')
            if kind == 'textarea':
                fields.append(
                    f'<label class="field">{esc(item.get("label", name))}'
                    f'<textarea name="{esc(name)}" rows="4"></textarea></label>'
                )
            elif kind == 'select':
                fields.append(
                    f'<label class="field">{esc(item.get("label", name))}'
                    f'<select name="{esc(name)}"></select></label>'
                )
            else:
                input_type = 'email' if kind == 'email' else (
                    'tel' if kind == 'phone' else ('number' if kind == 'number' else 'text')
                )
                required = ' required' if item.get('required') else ''
                fields.append(
                    f'<label class="field">{esc(item.get("label", name))}'
                    f'<input type="{input_type}" name="{esc(name)}"{required}></label>'
                )
    if records:
        # Форма с данными: показываем позиции, иначе заказ оформлялся бы
        # вслепую. Кнопка отправки остаётся: без бэкенда она никуда не
        # уйдёт, но разметка должна быть готова к подключению.
        fields = (
            '<ul class="cart">'
            + ''.join(f'<li class="cart__item">{esc(row)}</li>' for row in records)
            + '</ul>'
        )
    body = fields or '<p class="field">Поля появятся после настройки модуля.</p>'
    return (
        f'<section class="section section--form"><h2>{esc(title)}</h2>'
        f'<form method="{method}" action="{esc(action)}" class="form">{body}</form>'
        '</section>'
    )


def _render_media(block: dict) -> str:
    alt = _text(block, 'alt', _text(block, 'text', 'Изображение'))
    # Реальных файлов на стенде нет, и подставлять заглушку-снимок
    # значило бы отдать заказчику не его картинку. Плейсхолдер честнее:
    # он виден и в редакторе, и в экспорте.
    return (
        '<figure class="block block--media">'
        f'<div class="media__placeholder" role="img" aria-label="{esc(alt)}">'
        f'{esc(alt)}</div></figure>'
    )


def _render_button(block: dict) -> str:
    label = _text(block, 'label', _text(block, 'text', 'Кнопка'))
    href = _text(block, 'link', _text(block, 'href', '#'))
    return f'<a class="button" href="{esc(href)}">{esc(label)}</a>'


def _render_data(block: dict, records: list[dict] | None = None) -> str:
    """Блок данных: список записей источника или честный каркас.

    Пустой источник не заменяется выдуманными строками: заказчик
    должен видеть, что данных нет, а не то, что база пуста.
    """

    if not records:
        return (
            '<section class="section section--data">'
            '<p class="data__empty">Нет записей</p></section>'
        )
    items = ''.join(
        f'<li class="data__item">{esc(item)}</li>' for item in records
    )
    return (
        f'<section class="section section--data"><ul class="data">{items}</ul></section>'
    )


#: Модули, которые умеет отрисовать экспорт. Остальные 65 − 16 требуют
#: отдельной вёрстки, и молча пропускать их нельзя: пакет с дырой
#: выглядел бы готовым.
RENDERERS = {
    'section.hero': _render_section,
    'section.header': _render_section,
    'section.feature': _render_section,
    'section.footer': _render_section,
    'section.cards': _render_cards,
    'section.split': _render_split,
    'section.cta': _render_cta,
    'text.heading': lambda b: _render_heading(b, 2),
    'text.paragraph': _render_paragraph,
    'text.list': _render_list,
    'text.quote': _render_quote,
    'media.image': _render_media,
    'media.video': _render_media,
    'action.button': _render_button,
    'action.link': _render_button,
    'code.custom': lambda b: f'<pre class="block block--code">{esc(b.get("content"))}</pre>',
    # Отступ: в редакторе это пустое место, в пакете — тоже. Рендерить
    # его рамкой значило бы добавить на страницу то, чего в проекте нет.
    'action.form': _render_form,
    # Модули данных получают записи источника вторым аргументом.
    'data.collection': _render_data,
    'data.list': _render_data,
    'data.single': _render_data,
    'data.search': _render_data,
    'data.pagination': _render_data,
    # Отступ: в редакторе это пустое место, в пакете — тоже. Рисовать
    # его рамкой значило бы добавить на страницу то, чего в проекте нет.
    'section.spacer': lambda b: '<div class="block block--spacer" aria-hidden="true"></div>',
    'media.embed': _render_embed,
    'seo.schema': _render_schema,
    'nav.breadcrumb': _render_breadcrumbs,
    'nav.anchor': _render_anchor,
    'text.code': _render_code,
    'text.table': _render_table,
    'social.links': _render_social,
    'section.accordion': _render_accordion,
    'section.tabs': _render_tabs,
    'section.gallery': _render_gallery,
    'section.timeline': _render_timeline,
    'section.steps': _render_steps,
    'media.audio': _render_audio,
    'media.file': _render_file,
    'legal.age-mark': _render_age_mark,
    'legal.ad-mark': _render_ad_mark,
    'legal.consent': _render_consent,
    'legal.offer': _render_offer,
    'legal.policy': _render_policy,
    'legal.requisites': _render_requisites,
    'trust.review': _render_review,
    'trust.rating': _render_rating,
    'trust.logos': _render_logos,

    'data.field': _render_field,
    'data.count': _render_count,
    'data.aggregate': _render_aggregate,
    'data.sort': _render_data_sort,
    'data.filter': _render_data_filter,
    'data.related': _render_data_related,
    'data.form': _render_data_form,
    'shop.card': _render_data,
    'shop.catalog': _render_data,
    'shop.reviews': _render_review_list,
    'shop.price': _render_price,
    'promo.pricing': _render_data,
    'promo.banner': _render_section,
    'shop.order': _render_form,
    'shop.cart': _render_data,
    'shop.stock': _render_count,
    'shop.search': _render_form,
    'shop.checkout': _render_form,
    'shop.compare': _render_table_from_records,
}


def render_block(block: dict, records: list[dict] | None = None) -> RenderedBlock:
    """Один блок дерева в HTML.

    Неизвестный модуль считается ошибкой, а не пропуском: пакет без
    блока хуже, чем отказ экспорта.
    """

    module_id = block.get('module')
    if module_id not in MODULE_IDS:
        raise ExportError(f'Модуль «{module_id}» неизвестен реестру.')
    renderer = RENDERERS.get(module_id)
    if renderer is None:
        raise ExportError(f'Модуль «{module_id}» пока не умеет экспортироваться.')
    # Записи передаются всем модулям данных, а не только data.*:
    # коммерческие блоки (каталог, карточка товара, корзина) читают
    # тот же источник, и без записей они выводили бы пустую заглушку
    # на месте реального товара.
    needs_records = module_id.startswith('data.') or module_id.startswith(('shop.', 'promo.'))
    body = renderer(block, records or []) if needs_records else renderer(block)
    return RenderedBlock(block_id=str(block.get('id', '')), module_id=module_id, html=body)


def build_css(styles: dict[str, dict]) -> str:
    """Стили пакета из палитры и библиотеки компонентов.

    Файл один и без внешних ссылок: пакет должен открываться с любого
    хостинга и без интернета (п.16.4).
    """

    light = THEMES['light']
    def value(token: str, fallback: str) -> str:
        if token in light:
            return light[token]
        return token if token.startswith('#') else fallback

    def section_style(kind: str, fallback_fill: str) -> str:
        tokens = styles.get(kind) or {}
        fill = value(str(tokens.get('background', '')), fallback_fill)
        radius = int(tokens.get('radius', 8) or 0)
        padding = int(tokens.get('padding', 20) or 0)
        return (
            f'--fill-{kind}: {fill};'
            f'--radius-{kind}: {radius}px;'
            f'--padding-{kind}: {padding}px;'
        )

    variables = [
        f'--font: {light.get("textPrimary", "#1A1C1E") and "Inter, system-ui, sans-serif"}',
        section_style('section', light.get('panel', '#FFFFFF')),
        section_style('text', light.get('canvas', '#F7F8F9')),
        section_style('media', light.get('canvas', '#F7F8F9')),
        f'--accent: {light.get("accentSurface", "#D9A441")}',
        f'--on-accent: {light.get("onAccentSurface", "#1A1C1E")}',
        f'--text: {light.get("textPrimary", "#1A1C1E")}',
        f'--text-muted: {light.get("textSecondary", "#5B6169")}',
        f'--border: {light.get("borderStrong", "#C9CDD3")}',
    ]

    return f""":root {{
  {'\n  '.join(variables)}
}}

* {{ box-sizing: border-box; }}

body {{
  margin: 0;
  font-family: var(--font);
  color: var(--text);
  background: var(--fill-text);
  line-height: 1.5;
}}

.section {{
  background: var(--fill-section);
  border-radius: var(--radius-section);
  padding: var(--padding-section);
  margin: 0 0 24px;
}}

.section__title {{ margin: 0 0 8px; font-size: 24px; }}
.section__subtitle {{ margin: 0 0 16px; color: var(--text-muted); }}

.block--text {{ margin: 0 0 12px; }}
.block--media {{ margin: 0 0 16px; }}

.media__placeholder {{
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-media);
  color: var(--text-muted);
  background: var(--fill-media);
}}

.button {{
  display: inline-block;
  padding: 10px 20px;
  border-radius: 8px;
  background: var(--accent);
  color: var(--on-accent);
  text-decoration: none;
}}

.cards {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }}
.card {{ border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
.split {{ display: grid; gap: 24px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}

@media (prefers-color-scheme: dark) {{
  :root {{
    --fill-section: {THEMES['dark'].get('panel', '#16181B')};
    --fill-text: {THEMES['dark'].get('canvas', '#0E0F11')};
    --fill-media: {THEMES['dark'].get('canvas', '#0E0F11')};
    --text: {THEMES['dark'].get('textPrimary', '#F7F8F9')};
    --text-muted: {THEMES['dark'].get('textSecondary', '#A8AEB6')};
    --border: {THEMES['dark'].get('borderStrong', '#3A3E44')};
  }}
}}
"""