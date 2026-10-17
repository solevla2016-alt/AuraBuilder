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

from .module_registry import MODULE_IDS, MODULES_BY_ID
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



def _own(block: dict, name: str, fallback: str = '') -> str:
    """Значение свойства без подстановки подписи блока.

    _text для большинства модулей прав: поле «Название» в панели
    попадает в label, и подпись блока разумно считать заголовком.
    Но для содержимого это неверно: подпись блока не является текстом
    оферты, наименованием организации или названием компании из
    логотипов. Без этого выгрузка подставляла «Блок» вместо
    содержимого — тихо и очень заметно на готовом сайте.
    """
    value = _props(block).get(name)
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    if isinstance(value, (int, float)):
        return str(value)
    return fallback


def _items(block: dict, name: str, fallback: list[str]) -> list[str]:
    """Пункты многострочного свойства: список строк без пустых.

    Значение хранится одной строкой — так список занимает одно поле
    панели свойств, а не двадцать.

    Разделителей два: перевод строки и точка с запятой. Второй нужен
    для значения по умолчанию: оно записывается в документе схем в одну
    строку, и перевод строки туда не помещается. Если принимать только
    переводы строк, список из трёх пунктов пришлось бы хранить одним
    словом «Клиент».
    """
    raw = _own(block, name, '')
    if not raw:
        return list(fallback)
    parts = [item.strip() for chunk in raw.splitlines() for item in chunk.split(';')]
    parts = [item for item in parts if item]
    return parts or list(fallback)

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
    экрана хранится в панели свойств, а не в содержимое блока.
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
    """Якорь: пустая метка в разметке, к которой ведут ссылки меню.

    Подпись выводится только если она задана: пустая метка нужна для
    ссылок меню, а подпись — для навигации поиском по странице.
    """
    anchor = _own(block, 'anchor', '') or str(block.get('id', 'anchor'))
    label = _own(block, 'label', '')
    tail = f'<span class="visually-hidden">{esc(label)}</span>' if label else ''
    return f'<a id="{esc(anchor)}"></a>{tail}' 


def _render_breadcrumbs(block: dict) -> str:
    """Хлебные крошки из текста «Главная / Каталог / Розы»."""
    raw = _text(block, 'items') or _text(block, 'text') or 'Главная'
    parts = [p.strip() for p in raw.split('/') if p.strip()] or ['Главная']
    items = ''.join(f'<li>{esc(part)}</li>' for part in parts)
    return f'<nav class="breadcrumbs" aria-label="Хлебные крошки"><ol>{items}</ol></nav>'


def _render_accordion(block: dict) -> str:
    """Аккордеон на нативном <details>.

    Свойства читаются по схеме docs/MODULE-PROPS.md: заголовок секции
    и список вопросов по одному в строке. Раньше здесь ожидались title
    и text — другие имена, чем в схеме, поэтому заданные в редакторе
    вопросы в выгрузку не попадали и подставлялся вопрос по умолчанию.

    Ответ на вопрос пишется в той же строке после двоеточия:
    «Вопрос: ответ». Так один многострочный список хранит и заголовки,
    и содержимое панелей, а не два свойства, которые надо заполнять
    раздельно.
    """
    items = _items(block, "items", ["Как оформить заказ?", "Где доставка?"])
    first_open = _props(block).get("firstOpen") is not False
    heading = _text(block, "heading", "")

    parts = ["<section class=\"block block--accordion\">"]
    if heading:
        parts.append(f"<h2>{esc(heading)}</h2>")
    for i, item in enumerate(items):
        question, _, answer = item.partition(":")
        body = answer.strip() or "Ответ на вопрос."
        opened = " open" if first_open and i == 0 else ""
        parts.append(
            f"<details{opened}><summary>{esc(question.strip())}</summary>"
            f"<p>{esc(body)}</p></details>"
        )
    parts.append("</section>")
    return "".join(parts)


def _render_tabs(block: dict) -> str:
    """Вкладки.

    Переключение — CSS и нативный <details>: скрипт в статическом
    пакете не нужен, пакет должен работать без платформы. Подписи
    берутся из свойства tabs, как в схеме; раньше читался items,
    и заданные в редакторе подписи до выгрузки не доходили.
    """
    heading = _text(block, "heading", "")
    items = _items(block, "tabs", ["Подготовка", "Проверка", "Доставка"])
    limit = _props(block).get("columns")
    if isinstance(limit, int) and 2 <= limit <= 4:
        items = items[:limit]

    parts = ["<section class=\"block block--tabs\">"]
    if heading:
        parts.append(f"<h2>{esc(heading)}</h2>")
    parts.append("<div class=\"tabs\">")
    for item in items:
        parts.append(
            f"<details class=\"tabs__item\"><summary>{esc(item)}</summary>"
            f"<p>{esc(item)}</p></details>"
        )
    parts.append("</div></section>")
    return "".join(parts)


def _render_gallery(block: dict) -> str:
    """Галерея: файлы из свойства images либо честные заглушки.

    Раскладка задаётся схемой: сколько кадров в ряд (columns) и
    промежуток (gap). Если файлов нет или их меньше, чем кадров
    раскладки, недостающие места занимает заглушка — иначе сетка
    «схлопывается» и страница выглядит сломанной.
    """
    props = _props(block)
    heading = _text(block, "heading", "")
    columns = props.get("columns")
    columns = columns if isinstance(columns, int) and 2 <= columns <= 5 else 3
    gap = props.get("gap")
    gap = gap if isinstance(gap, int) and 4 <= gap <= 48 else 16
    frames = props.get("frames")
    frames = frames if isinstance(frames, int) and 2 <= frames <= 24 else columns

    images = _split_images(props.get("images"))
    cells = []
    for index in range(frames):
        src = images[index] if index < len(images) else ''
        if src:
            body = _image_tag(src, f'Изображение {index + 1}')
        else:
            body = (
                f'<div class="media__placeholder" role="img" '
                f'aria-label="Изображение {index + 1}">'
                f'Изображение {index + 1}</div>'
            )
        cells.append(f'<figure class="gallery__item">{body}</figure>')
    grid = "".join(cells)

    style = f' style="--gallery-columns:{columns};--gallery-gap:{gap}px"'
    heading_html = f'<h2 class="gallery__heading">{esc(heading)}</h2>' if heading else ''
    return (
        '<section class="block block--gallery">'
        f'{heading_html}'
        f'<div class="gallery__grid"{style}>{grid}</div>'
        '</section>'
    )


def _render_timeline(block: dict) -> str:
    """Таймлайн: год первого события и шаг между годами.

    Список лет не хранится: пользователь задаёт начало и шаг, а
    подписи событий — по одной на событие (event0, event1). Так годы
    не расходятся с подписями и не требуют дублирования.
    """
    props = _props(block)
    heading = _text(block, "heading", "")
    year = props.get("year")
    year = year if isinstance(year, int) else 2019
    step = props.get("stepYears")
    step = step if isinstance(step, int) and 1 <= step <= 10 else 2
    count = props.get("events")
    count = count if isinstance(count, int) and 2 <= count <= 8 else 4

    entries = "".join(
        f'<li class="timeline__item"><span class="timeline__year">{year + step * i}</span>'
        f"<span>{esc(_text(block, f'event{i}', 'Событие'))}</span></li>"
        for i in range(count)
    )
    return (
        "<section class=\"block block--timeline\">"
        + (f"<h2>{esc(heading)}</h2>" if heading else "")
        + f'<ol class="timeline">{entries}</ol></section>'
    )


def _render_steps(block: dict) -> str:
    """Шаги по шаблону: название шага на строку.

    Номера отключаются свойством showNumbers — иногда нужны сами шаги
    без нумерации, например когда они подписаны на картинке.
    """
    props = _props(block)
    heading = _text(block, "heading", "")
    items = _items(block, "steps", ["Заявка", "Согласование", "Работа"])
    numbers = props.get("showNumbers") is not False

    entries = "".join(
        f'<li class="steps__item">'
        + (f'<span class="steps__num">{i + 1}</span>' if numbers else "")
        + f"<span>{esc(item)}</span></li>"
        for i, item in enumerate(items)
    )
    return (
        "<section class=\"block block--steps\">"
        + (f"<h2>{esc(heading)}</h2>" if heading else "")
        + f'<ol class="steps">{entries}</ol></section>'
    )


def _render_audio(block: dict) -> str:
    """Аудиозапись.

    Плеер появляется только когда задан src: подставлять чужой файл
    нельзя, посетитель получил бы битый плеер. Без src остаётся
    подпись с местом под файл.
    """
    title = _own(block, 'title', 'Аудио')
    src = _own(block, 'src', '')
    if not src:
        return (
            '<figure class="block block--audio">'
            f'<figcaption class="media__placeholder">{esc(title)}</figcaption>'
            '<figcaption class="media__note">Аудиофайл не подключён.</figcaption>'
            '</figure>'
        )
    autoplay = _props(block).get('autoplay') is True
    loop = _props(block).get('loop') is True
    flags = ''
    if autoplay:
        flags += ' autoplay'
    if loop:
        flags += ' loop'
    return (
        '<figure class="block block--audio">'
        f'<figcaption>{esc(title)}</figcaption>'
        f'<audio controls src="{esc(src)}"{flags}></audio>'
        '</figure>'
    )


def _render_code(block: dict) -> str:
    """Блок кода.

    Текст берётся из свойства code: раньше читалось внутреннее поле
    content, которого нет в панели свойств, и код нельзя было задать
    из редактора — в выгрузку попадало пустое значение.
    """
    heading = _own(block, 'heading', '')
    language = _own(block, 'language', 'js')
    body = _own(block, 'code', '')
    head = f'<h3>{esc(heading)}</h3>' if heading else ''
    return (
        f'<section class="block block--code" data-language="{esc(language)}">'
        f'{head}<pre><code>{esc(body)}</code></pre></section>'
    )


def _render_social(block: dict) -> str:
    """Ссылки на соцсети: по одному адресу в строке.

    Адреса хранятся текстом, а не списком href в настройках: список
    означал бы, что экспорт должен ходить в сеть за разбором ссылок,
    а пакет должен собираться без сети.
    """
    heading = _own(block, 'heading', '')
    links = _items(block, 'links', ['https://example.com/social'])
    items = ''.join(f'<li><a href="{esc(link)}">{esc(link)}</a></li>' for link in links)
    head = f'<h2>{esc(heading)}</h2>' if heading else ''
    return (
        '<section class="block block--social">'
        f'{head}<ul class="social">{items}</ul></section>'
    )


def _render_table(block: dict) -> str:
    """Таблица из текста: первая строка — заголовки.

    Раньше содержимое бралось из внутреннего поля content, которого
    нет в панели свойств, и таблицу нельзя было заполнить из
    редактора. Столбцы разделены точкой с запятой, строки — переводом
    строки; разделитель выбран тот же, что у списков.
    """
    heading = _own(block, 'heading', '')
    raw = _own(block, 'rows', '')
    lines = [line.strip() for line in raw.splitlines() if line.strip()]

    # Таблица выводится даже пустой: на странице под неё отведено
    # место, и исчезновение таблицы оставляет дыру в вёрстке.
    if not lines:
        return (
            '<section class="block block--table"><table>'
            '<thead><tr><th scope="col"></th></tr></thead>'
            '<tbody></tbody></table>'
            '<p class="data__empty">Таблица пуста.</p></section>'
        )

    header = [c.strip() for c in lines[0].split(';') if c.strip()]
    if not header:
        header = [' ']
    head_html = ''.join(f'<th scope="col">{esc(c)}</th>' for c in header)
    body = ''
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(';') if c.strip()]
        # Недостающие столбцы дополняются пустыми: иначе строки разъезжаются,
        # и таблица выглядит битой из-за одного пустого значения.
        padded = cells + [''] * (len(header) - len(cells))
        body += '<tr>' + ''.join(f'<td>{esc(c)}</td>' for c in padded[:len(header)]) + '</tr>'

    head_block = f'<h2>{esc(heading)}</h2>' if heading else ''
    return (
        '<section class="block block--table">'
        f'{head_block}<table><thead><tr>{head_html}</tr></thead>'
        f'<tbody>{body}</tbody></table></section>'
    )


def _render_file(block: dict) -> str:
    """Файл для скачивания.

    Без href ссылка ведёт в никуда, и посетитель нажимает и получает
    пустую страницу. В этом случае показывается подпись без ссылки.
    """
    title = _own(block, 'title', 'Файл')
    href = _own(block, 'href', '')
    size = _own(block, 'size', '')
    tail = f'<span class="file__size">{esc(size)}</span>' if size else ''
    if not href:
        return (
            f'<div class="block block--file"><span class="file__name">{esc(title)}</span>'
            f'{tail}<span class="file__note">Файл не прикреплён.</span></div>'
        )
    return (
        f'<a class="block block--file" href="{esc(href)}" download>'
        f'<span class="file__name">{esc(title)}</span>{tail}</a>'
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
    него площадка может отклонить публикацию. Рамка вокруг знака
    обязательна тоже — маркировка должна читаться явно.
    """
    text = _own(block, 'text', '18+')
    note = _own(block, 'note', '')
    tail = f'<small>{esc(note)}</small>' if note else ''
    return (
        '<div class="legal age-mark">'
        f'<span class="legal age-mark__sign" role="img" aria-label="{esc(text)}">{esc(text)}</span>'
        f'{tail}</div>'
    )


def _render_ad_mark(block: dict) -> str:
    """Маркировка рекламы (ТЗ п.9.5).

    Имена свойств приведены к схеме: раньше читались label и link,
    которых в схеме нет, — вместо них были text, href и label. Из-за
    этого пометка выводилась подписью блока, а надпись о маркировке
    до выгрузки не доходила вовсе.

    Пометка отделяется рамкой: по ТЗ её должно быть видно, что это
    реклама, а не часть контента.
    """
    text = _own(block, 'text', 'Реклама')
    href = _own(block, 'href', '')
    label = _own(block, 'label', '')

    inner = esc(f'{text} · {label}') if label else esc(text)
    body = f'<a href="{esc(href)}">{inner}</a>' if href else inner
    return f'<div class="legal ad-mark">{body}</div>'


def _render_consent(block: dict) -> str:
    """Согласие на обработку персональных данных.

    Ссылка обязательна: без неё форма отправляет данные без правового
    основания, и это останавливает публикацию магазина.

    Флажок обязателен по умолчанию: свойство required снимает его явно,
    и молчаливое отсутствие галочки было бы нарушением закона.
    """
    text = _own(block, 'text', 'Я согласен на обработку персональных данных')
    href = _own(block, 'link', '/privacy-policy')
    required = _props(block).get('required') is not False
    flag = '<input type="checkbox" required>' if required else '<input type="checkbox">'
    return (
        '<p class="legal consent">'
        f'<label>{flag} {esc(text)} '
        f'<a href="{esc(href)}">политика</a></label></p>'
    )


def _render_review(block: dict) -> str:
    """Отзыв: оценка, текст, автор.

    Раньше всё три поля читались из одного свойства через разделитель
    «|», которого нет в схеме: author, rating и text настраивались
    по отдельности и в выгрузку не попадали.
    """
    author = _own(block, 'author', '')
    body = _own(block, 'text', '')
    rating = _props(block).get('rating')
    rating = int(rating) if isinstance(rating, (int, float)) else 5
    stars = '★' * max(0, min(5, rating))
    return (
        '<figure class="review block">'
        f'<blockquote>{esc(body)}</blockquote>'
        f'<figcaption>{stars} · {esc(author)}</figcaption></figure>'
    )


def _render_rating(block: dict) -> str:
    """Рейтинг: оценка, число отзывов, источник."""
    value = _props(block).get('value')
    value = value if isinstance(value, (int, float)) else 4.8
    count = _props(block).get('count')
    count = int(count) if isinstance(count, (int, float)) else 120
    source = _own(block, 'source', '')
    tail = f' отзывов' + (f' · {esc(source)}' if source else '')
    return (
        f'<div class="rating block"><b>{value}</b> · {count}{tail}</div>'
    )


def _render_logos(block: dict) -> str:
    """Логотипы клиентов: названия плейсхолдером."""
    heading = _text(block, 'heading', 'Нам доверяют')
    items = _items(block, 'items', ['Клиент', 'Клиент', 'Клиент'])
    cells = "".join(
        f'<div class="logos__item media__placeholder">{esc(item)}</div>' for item in items
    )
    return (
        '<section class="section section--trust section--logos">'
        + (f'<h2>{esc(heading)}</h2>' if heading else '')
        + f'<div class="logos">{cells}</div></section>'
    )


def _render_legal_document(block: dict, kind: str) -> str:
    """Юридический документ: оферта или политика конфиденциальности.

    Раньше здесь выводилась строка «Текст оферты.» / «Текст политики.»:
    пользователь вставлял документ в редакторе, а в выгрузку попадала
    заглушка. Для юридического документа это хуже всего — на сайте
    заказчика оказывался чужой текст, который выглядит настоящим.

    Текст выводится по абзацам: переводы строк сохраняются, иначе
    документ слипся бы в одну простыню.
    """
    default_heading = 'Публичная оферта' if kind == 'offer' else 'Политика конфиденциальности'
    heading = _text(block, 'heading', default_heading)
    body = _own(block, 'body', '')
    updated = _own(block, 'updated', '')

    paragraphs = [
        f'<p>{esc(chunk.strip())}</p>'
        for chunk in body.splitlines()
        if chunk.strip()
    ]

    return (
        f'<section class="section section--legal" id="{kind}">'
        f'<h2>{esc(heading)}</h2>'
        + (f'<p class="legal__updated">Редакция от {esc(updated)}</p>' if updated else '')
        + ("".join(paragraphs) or f'<p>{esc(_default_legal_text(kind))}</p>')
        + '</section>'
    )


def _default_legal_text(kind: str) -> str:
    """Текст-заглушка с явным упоминанием, что его надо заменить."""
    if kind == 'offer':
        return 'Текст оферты не заполнен. Заполните поле «Текст оферты» в редакторе.'
    return (
        'Текст политики конфиденциальности не заполнен. '
        'Заполните поле в редакторе до публикации.'
    )


def _render_offer(block: dict) -> str:
    return _render_legal_document(block, 'offer')


def _render_policy(block: dict) -> str:
    return _render_policy_document(block)


def _render_policy_document(block: dict) -> str:
    return _render_legal_document(block, 'policy')


def _render_requisites(block: dict) -> str:
    """Реквизиты: строкой по полям, без абзаца прозы.

    ИНН, ОГРН и адрес проверяют при закупке, и в абзаце их не найти.
    Пустые строки пропускаются: пустой ОГРН — это отсутствие ОГРН,
    а не «ОГРН: —».
    """
    heading = _text(block, 'heading', 'Реквизиты')
    rows = [
        ('Наименование', _own(block, 'name', '')),
        ('ИНН', _own(block, 'inn', '')),
        ('ОГРН', _own(block, 'ogrn', '')),
        ('Адрес', _own(block, 'address', '')),
        ('Почта', _own(block, 'email', '')),
    ]
    body = "".join(
        f'<div class="requisites__row"><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>'
        for label, value in rows
        if value
    )
    return (
        '<section class="section section--legal section--requisites">'
        f'<h2>{esc(heading)}</h2>'
        f'<dl class="requisites">{body}</dl></section>'
    )


def _render_reviews(block: dict, records: list[dict] | None = None,
                    dataset: list[dict] | None = None) -> str:
    """Отзывы о товаре: оценка, текст и автор.

    Раньше выводились готовые строки без автора и оценки: имя
    покупателя терялось, и отзыв читался как анонимный.
    """
    author_field = _own(block, 'authorField', 'author')
    text_field = _own(block, 'textField', 'text')
    rating_field = _own(block, 'ratingField', 'rating')
    limit = _int_prop(block, 'limit', 10, 1, 50)

    rows = list(dataset if dataset is not None else [])[:limit]
    if not rows:
        return (
            '<section class="section section--reviews">'
            '<p class="data__empty">Отзывов нет.</p></section>'
        )

    items = ''
    for row in rows:
        author = str(row.get(author_field) or 'Покупатель')
        body = str(row.get(text_field) or '')
        raw_rating = row.get(rating_field) if rating_field else None
        numbers = _numbers([raw_rating]) if raw_rating is not None else []
        stars = '★' * max(0, min(5, int(numbers[0]))) if numbers else ''
        items += (
            '<li class="review">'
            f'<blockquote>{esc(body)}</blockquote>'
            f'<figcaption>{stars} · {esc(author)}</figcaption></li>'
        )

    return (
        '<section class="section section--reviews">'
        f'<ul class="reviews">{items}</ul>'
        f'<p class="data__note">Показано {len(rows)}</p></section>'
    )


def _render_compare(block: dict, records: list[dict] | None = None,
                   dataset: list[dict] | None = None) -> str:
    """Сравнение товаров: товары по строкам, поля по столбцам.

    Порядок полей задан настройкой и сохраняется как есть:
    разложить признаки случайно значило бы сравнить несравнимое.
    """
    title_field = _own(block, 'titleField', 'title')
    price_field = _own(block, 'priceField', '')
    keys = _items(block, 'fields', ['price', 'weight'])
    limit = _int_prop(block, 'limit', 4, 2, 12)
    button = _own(block, 'buttonLabel', '')

    rows = list(dataset if dataset is not None else [])[:limit]
    if not rows:
        return (
            '<section class="section section--compare">'
            '<p class="data__empty">Нечего сравнивать.</p></section>'
        )

    head = ''.join(f'<th scope="col">{esc(key)}</th>' for key in keys)
    first_head = '<th scope="col">товар</th>'
    tail_head = '<th scope="col"></th>' if button else ''
    body = ''
    for row in rows:
        cells = ''.join(
            f'<td>{esc(_price_of(row, key) if key == price_field else row.get(key, ""))}</td>'
            for key in keys
        )
        name = esc(row.get(title_field) or 'Товар')
        action = f'<span class="product__action">{esc(button)}</span>' if button else ''
        body += f'<tr><th scope="row">{name}</th>{cells}{action}</tr>'

    return (
        '<section class="section section--compare">'
        '<table class="compare"><thead><tr>'
        f'{first_head}{head}{tail_head}'
        '</tr></thead>'
        f'<tbody>{body}</tbody></table></section>'
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


def _render_count(block: dict, records: list[dict] | None = None,
                 dataset: list[dict] | None = None) -> str:
    """Счётчик записей или значений одного поля.

    Пустое поле означает «столько записей», заполненное — «столько
    записей, где это поле заполнено». Второе полезно для блока, где
    показывают готовые записи: считать все подряд нельзя.
    """
    field = _own(block, 'field', '')
    label = _own(block, 'label', 'Всего')
    rows = dataset or list(records or [])

    if field:
        total = sum(1 for row in rows if field in row and str(row.get(field) or '').strip())
    else:
        total = len(rows)

    return (
        '<section class="section section--data">'
        f'<p class="data__count"><span class="data__count-value">{total}</span>'
        f'<span class="data__count-label">{esc(label)}</span></p></section>'
    )


def _render_stock(block: dict, records: list[dict] | None = None,
                  dataset: list[dict] | None = None) -> str:
    """Остаток товара на момент публикации.

    Остаток меняется каждый день, а статический пакет собирается
    один: число честно, но датировано. Подпись под ним обязательна —
    молчаливое число выглядело бы как актуальный остаток.
    """
    field = _own(block, 'field', 'stock')
    label = _own(block, 'label', 'Осталось')
    threshold = _int_prop(block, 'lowThreshold', 5, 0, 1000)
    note = _own(block, 'note', 'Данные на момент публикации')

    rows = list(dataset if dataset is not None else [])
    values = _numbers([row.get(field) for row in rows])
    total = int(sum(values)) if values else 0

    classes = 'stock stock--low' if 0 < total <= threshold else 'stock'
    if total <= 0:
        classes = 'stock stock--out'

    return (
        '<section class="section section--stock">'
        f'<p class="{classes}"><span class="stock__value">{total}</span>'
        f'<span class="stock__label">{esc(label)}</span></p>'
        f'<p class="stock__note">{esc(note)}</p></section>'
    )


def _int_prop(block: dict, name: str, fallback: int, low: int, high: int) -> int:
    """Числовое свойство в границах: значение из настроек может быть любым."""
    value = _props(block).get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return fallback
    return max(low, min(high, int(value)))


def _price_of(row: dict, field: str) -> str:
    """Цена записи: значение поля либо прочерк, если поля нет."""
    value = row.get(field)
    if value in (None, ''):
        return '\u2014'
    text = str(value).strip()
    return text or '\u2014'


def _product_card(row: dict, title_field: str, price_field: str,
                  image_field: str, detail_field: str, button: str,
                  price_prefix: str, item_id: str = '') -> str:
    """Карточка товара из одной записи.

    Ключи полей задаёт пользователь: в источнике имена произвольны, и
    без явного указания нельзя отличить название от цены.
    """
    title = str(row.get(title_field) or 'Товар')
    price = _price_of(row, price_field) if price_field else ''
    image = str(row.get(image_field) or '') if image_field else ''
    detail = str(row.get(detail_field) or '') if detail_field else ''

    picture = (
        f'<img class="product__image" src="{esc(image)}" alt="{esc(title)}" loading="lazy">'
        if image
        else '<div class="product__image media__placeholder" role="img" '
             f'aria-label="{esc(title)}"></div>'
    )
    price_html = ''
    if price and price != '\u2014':
        money = f'{price_prefix} {price}'.strip() if price_prefix else price
        price_html = f'<p class="product__price">{esc(money)}</p>'
    detail_html = f'<p class="product__detail">{esc(detail)}</p>' if detail else ''
    label = esc(button) if button else ''

    # Кнопка появляется только вместе с идентификатором товара: без
    # него нажатие некуда отправить, и кнопка была бы обещанием.
    if item_id:
        add = (
            f'<button type="button" class="product__action" data-rt-add="{esc(item_id)}">'
            f'{label or "В корзину"}</button>'
        )
    elif label:
        add = f'<span class="product__action">{label}</span>'
    else:
        add = ''

    return (
        '<article class="product">'
        f'{picture}<h3 class="product__title">{esc(title)}</h3>'
        f'{price_html}{detail_html}'
        f'{add}'
        '</article>'
    )


def _render_promo_banner(block: dict, records: list[dict] | None = None) -> str:
    """Промо-баннер.

    Раньше баннер выводился тем же разделом, что первый экран: не
    было ни кнопки, ни выравнивания, и баннер не отличался от
    обычной секции. Отличать его должна заливка — иначе посетитель
    не видит, что перед ним предложение, а не содержимое страницы.
    """
    heading = _own(block, 'heading', '')
    body = _own(block, 'text', '')
    button = _own(block, 'buttonLabel', '')
    link = _own(block, 'link', '') or _own(block, 'buttonLink', '')
    align = _own(block, 'align', 'left')
    background = _own(block, 'background', 'light')

    parts = [f'<section class="banner banner--{esc(align)} banner--{esc(background)}">']
    if heading:
        parts.append(f'<h2>{esc(heading)}</h2>')
    if body:
        parts.append(f'<p>{esc(body)}</p>')
    if button:
        target = esc(link) if link and link != '#' else '#'
        parts.append(f'<a class="banner__action" href="{target}">{esc(button)}</a>')
    parts.append('</section>')
    return ''.join(parts)


def _render_pricing(block: dict, records: list[dict] | None = None,
                    dataset: list[dict] | None = None) -> str:
    """Тарифы: карточки с ценой, периодом и списком включений.

    Раньше был списком строк, как data.list: посетитель не видел,
    где один тариф лучше другого.
    """
    title_field = _own(block, 'titleField', 'title')
    price_field = _own(block, 'priceField', 'price')
    period_field = _own(block, 'periodField', '')
    features_field = _own(block, 'featuresField', '')
    highlight_field = _own(block, 'highlight', '')

    rows = list(dataset if dataset is not None else [])

    def card(row: dict) -> str:
        title = str(row.get(title_field) or 'Тариф')
        price = _price_of(row, price_field) if price_field else ''
        period = str(row.get(period_field) or '') if period_field else ''
        features = str(row.get(features_field) or '') if features_field else ''
        highlight = str(row.get(highlight_field) or '').lower() if highlight_field else ''

        price_html = f'<p class="plan__price">{esc(price)}</p>' if price else ''
        period_html = f'<p class="plan__period">{esc(period)}</p>' if period else ''
        items = ''.join(
            f'<li>{esc(part.strip())}</li>'
            for part in features.split(';')
            if part.strip()
        )
        features_html = f'<ul class="plan__features">{items}</ul>' if items else ''
        mark = ' plan--highlight' if highlight in ('1', '1.0', 'true', 'да') else ''
        return (
            f'<article class="plan{mark}">'
            f'<h3 class="plan__title">{esc(title)}</h3>'
            f'{price_html}{period_html}{features_html}'
            '</article>'
        )

    cards = ''.join(card(row) for row in rows)
    if not cards:
        cards = '<p class="data__empty">Тарифы не заданы.</p>'

    return (
        '<section class="section section--pricing">'
        f'<div class="plans">{cards}</div></section>'
    )


def _render_catalog(block: dict, records: list[dict] | None = None,
                    dataset: list[dict] | None = None) -> str:
    """Каталог товаров.

    Раньше был тем же списком, что data.list: карточек не было, и
    посетитель видел сплошной текст вместо товаров.
    """
    title_field = _own(block, 'titleField', 'title')
    price_field = _own(block, 'priceField', 'price')
    image_field = _own(block, 'imageField', '')
    columns = _int_prop(block, 'columns', 3, 2, 4)
    limit = _int_prop(block, 'limit', 12, 1, 100)

    rows = list(dataset if dataset is not None else [])
    shown = rows[:limit]
    # Идентификатор товара — его номер в источнике начиная с 1: он
    # должен совпасть с тем, что рантайм загрузит в каталог
    # (docs/RUNTIME.md). Номер считается по полному списку, а не по
    # обрезанному: иначе limit сдвинул бы идентификаторы и «В корзину»
    # отправила бы несуществующий товар.
    cards = ''.join(
        _product_card(row, title_field, price_field, image_field, '', '',
                      '', item_id=f't{index + 1}')
        for index, row in enumerate(rows[:limit])
    )
    if not cards:
        cards = '<p class="data__empty">Каталог пуст.</p>'

    return (
        '<section class="section section--catalog">'
        f'<div class="catalog" style="--catalog-columns:{columns}">{cards}</div>'
        f'<p class="data__note">Показано {len(shown)} из {len(rows)}</p>'
        '</section>'
    )


def _render_card(block: dict, records: list[dict] | None = None,
                 dataset: list[dict] | None = None) -> str:
    """Карточка одного товара: первая запись источника."""
    title_field = _own(block, 'titleField', 'title')
    price_field = _own(block, 'priceField', 'price')
    image_field = _own(block, 'imageField', '')
    detail_field = _own(block, 'detailField', '')
    button = _own(block, 'buttonLabel', 'Подробнее')
    prefix = _own(block, 'pricePrefix', '')

    rows = list(dataset if dataset is not None else [])
    if not rows:
        return (
            '<section class="section section--product">'
            '<p class="data__empty">Товар не выбран.</p></section>'
        )

    return (
        '<section class="section section--product">'
        + _product_card(rows[0], title_field, price_field, image_field,
                        detail_field, button, prefix, item_id='t1')
        + '</section>'
    )


def _render_price(block: dict, records: list[dict] | None = None,
                  dataset: list[dict] | None = None) -> str:
    """Цена товара.

    Раньше выводилась первая строка источника целиком: вместе с ценой
    посетитель видел название и всё остальное. Теперь берётся поле,
    указанное в настройках, и добавляются единица и «от».
    """
    field = _own(block, 'field', 'price')
    prefix = _own(block, 'prefix', '')
    suffix = _own(block, 'suffix', '\u20bd')
    show_old = _props(block).get('showOld') is True

    rows = list(dataset if dataset is not None else [])
    if rows:
        value = _price_of(rows[0], field)
    else:
        value = _own(block, 'value', '') or '\u2014'

    if value == '\u2014':
        return (
            '<section class="section section--price">'
            '<p class="price">\u2014</p></section>'
        )

    money = f'{value} {suffix}'.strip() if suffix else value
    old_value = _own(block, 'oldValue', '')
    old = (
        f'<s class="price__old">{esc(old_value)}</s>'
        if show_old and old_value
        else ''
    )
    return (
        '<section class="section section--price">'
        + (f'<span class="price__prefix">{esc(prefix)}</span>' if prefix else '')
        + f'<span class="price__value">{esc(money)}</span>'
        + old
        + '</section>'
    )


def _numbers(values: list[Any]) -> list[float]:
    """Числа из значений поля: строки разбираются, мусор пропускается."""
    out: list[float] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out.append(float(value))
            continue
        text = str(value).strip().replace('\u00a0', '').replace(' ', '')
        if not text:
            continue
        cleaned = ''.join(c for c in text if c.isdigit() or c in '.,-')
        if not cleaned or cleaned in ('-', '.', ','):
            continue
        try:
            out.append(float(cleaned.replace(',', '.')))
        except ValueError:
            continue
    return out


def _format_number(value: float) -> str:
    """Число без лишних нулей: 12 вместо 12.00, 12.5 вместо 12.50."""
    text = f'{value:.2f}'.rstrip('0').rstrip('.')
    return text or '0'


def _dataset_rows(dataset: list[dict], field: str, rows: list[dict]) -> list[dict]:
    """Записи по полю. Пустой ключ означает «все записи»."""
    if not field:
        return list(rows)
    return [row for row in dataset if field in row]


def _render_aggregate(block: dict, records: list[dict] | None = None,
                      dataset: list[dict] | None = None) -> str:
    """Итог по полю источника.

    Раньше суммировались все цифры во всех полях записи: телефон
    +7 999 прибавлялся к сумме заказа. Считать нужно по конкретному
    полю, и значения берутся из записей по ключам, а не из текста.
    """
    field = _own(block, 'field', 'title')
    op = _own(block, 'op', 'sum')
    label = _own(block, 'label', 'Итого')
    suffix = _own(block, 'suffix', '')

    values = _numbers([row.get(field) for row in (dataset or [])])

    if op == 'count' or not field:
        result = float(len(dataset or []))
    elif not values:
        result = None
    elif op == 'avg':
        result = sum(values) / len(values)
    elif op == 'min':
        result = min(values)
    elif op == 'max':
        result = max(values)
    else:
        result = sum(values)

    if result is None:
        shown = '\u2014'
    else:
        shown = _format_number(result) + (f' {suffix}' if suffix else '')

    return (
        f'<p class="aggregate block"><span class="aggregate__label">{esc(label)}</span>'
        f'<span class="aggregate__value">{esc(shown)}</span></p>'
    )


def _render_data_sort(block: dict, records: list[dict] | None = None,
                      dataset: list[dict] | None = None) -> str:
    """Сортировка фиксируется в пакете: рантайма нет.

    Порядок записей вычисляется при сборке, и в пакет попадает уже
    отсортированный список. На статическом сайте иначе некуда.
    """
    field = _own(block, 'field', 'title')
    direction = _own(block, 'direction', 'asc')
    props = _props(block)
    limit = props.get('limit')
    limit = int(limit) if isinstance(limit, (int, float)) else 10
    limit = max(1, min(100, limit))

    rows = list(dataset if dataset is not None else [])
    numeric = _numbers([row.get(field) for row in rows])
    by_number = len(numeric) == len([r for r in rows if r.get(field) not in (None, '')])

    if by_number:
        rows.sort(key=lambda row: _numbers([row.get(field)]) or [0.0])
    else:
        rows.sort(key=lambda row: str(row.get(field, '')).lower())

    if direction == 'desc':
        rows.reverse()

    shown = rows[:limit]
    items = ''.join(
        '<li>' + esc(' · '.join(str(v) for v in row.values() if v not in (None, ''))) + '</li>'
        for row in shown
    )
    body = f'<ul class="data">{items}</ul>' if items else '<p class="data__empty">Нет записей</p>'
    return (
        '<section class="section section--data" data-sort="'
        f"{esc(field)} {esc(direction)}>"
        + f"{body}"
        f'<p class="data__note">Показано {len(shown)} из {len(rows)}</p>'
        '</section>'
    )


def _render_data_related(block: dict, records: list[dict] | None = None,
                        dataset: list[dict] | None = None) -> str:
    """Связанные записи: карточки с заголовком из одного поля."""
    field = _own(block, 'field', '')
    title_field = _own(block, 'titleField', '')
    props = _props(block)
    limit = props.get('limit')
    limit = int(limit) if isinstance(limit, (int, float)) else 4
    limit = max(1, min(24, limit))

    rows = list(dataset if dataset is not None else [])
    if field:
        keys = {str(row.get(field) or '').strip() for row in rows if row.get(field)}
        rows = [row for row in rows if not keys or str(row.get(field) or '').strip() in keys]

    shown = rows[:limit]
    cards = ''.join(
        f'<article class="related__card"><h3>{esc(row.get(title_field) or "Запись")}</h3>'
        f'<p>{esc(" · ".join(str(v) for v in row.values() if v not in (None, "")))}</p></article>'
        for row in shown
    )
    body = cards if cards else '<p class="data__empty">Нет записей</p>'
    return f'<section class="section section--data">{body}</section>' 


def _render_data_filter(block: dict, records: list[dict] | None = None,
                       dataset: list[dict] | None = None) -> str:
    """Фильтр по полю: в статике отбор выполняется при сборке.

    Раньше фильтр не работал вовсе и печатал подпись о том, что
    «заработает после подключения бэкенда». Условие известно на этапе
    сборки, выполнять его на сервере не нужно: пакет и есть результат.
    """
    field = _own(block, 'field', 'title')
    operator = _own(block, 'operator', 'eq')
    value = _own(block, 'value', '')
    label = _own(block, 'label', '')

    rows = list(dataset if dataset is not None else [])

    def keep(row: dict) -> bool:
        current = str(row.get(field, '') or '')
        if operator == 'contains':
            return value in current
        if operator == 'gt':
            left, right = _numbers([current]), _numbers([value])
            return bool(left and right and left[0] > right[0])
        if operator == 'lt':
            left, right = _numbers([current]), _numbers([value])
            return bool(left and right and left[0] < right[0])
        if not value:
            return current != ''
        return current == value

    selected = [row for row in rows if keep(row)]
    items = ''.join(
        '<li>' + esc(' · '.join(str(v) for v in row.values() if v not in (None, ''))) + '</li>'
        for row in selected
    )
    heading = f'<h2>{esc(label)}</h2>' if label else ''
    body = f'<ul class="data">{items}</ul>' if items else '<p class="data__empty">Нет записей</p>'
    condition = esc(f'{field} {operator} {value}'.strip())
    return (
        '<section class="section section--data" data-filter="'
        f"{condition}>"
        f'{heading}{body}'
        f'<p class="data__filter-note">Отобрано {len(selected)} из {len(rows)}</p>'
        '</section>'
    )


def _render_data_form(block: dict, records: list[dict] | None = None,
                      dataset: list[dict] | None = None) -> str:
    """Форма записи из узла данных.

    Обработчика нет: отправлять значения некуда, поэтому форма только
    собирает их, а подпись говорит об этом прямо.

    Поля берутся из свойства fields, а не из первой записи: имена
    полей в источнике — это ключи (title, price), а в форме нужны
    подписи, которые задаёт пользователь.
    """
    heading = _own(block, 'heading', 'Форма')
    submit = _own(block, 'submitLabel', 'Отправить')
    note = _own(block, 'note', '')
    names = _items(block, 'fields', ['Имя', 'Телефон'])

    rows = list(dataset if dataset is not None else [])
    inputs = ''.join(
        f'<label class="field">{esc(name)}<input name="f{index}" '
        f'required></label>'
        for index, name in enumerate(names)
    )
    tail = (
        f'<p class="data__note">{esc(note)}</p>' if note
        else '<p class="data__note">Отправка заработает после подключения бэкенда.</p>'
    )
    return (
        '<section class="section section--data"><h2>'
        f'{esc(heading)}</h2>'
        f'<form class="form" method="post">{inputs}'
        f'<button type="submit">{esc(submit)}</button></form>{tail}</section>'
    )


RUNTIME_KINDS = {
    'shop.cart': 'cart',
    'shop.checkout': 'checkout',
    'shop.search': 'search',
}

# Разметка рабочего блока кладётся в статику сразу, но скрыта: без
# рантайма её нечем наполнить, и пустой список товаров выглядел бы
# как «магазин пуст». Клиент показывает её, только убедившись, что
# сервер отвечает (docs/RUNTIME.md).
_RUNTIME_TEMPLATES = {
    'cart': (
        '<div class="rt-cart" hidden>'
        '<ul class="rt-cart__items"></ul>'
        '<p class="rt-cart__total">Итого: <span class="rt-cart__total-value">—</span></p>'
        '<p class="rt-note" role="status"></p>'
        '</div>'
    ),
    'checkout': (
        '<form class="rt-form" hidden>'
        '<label class="rt-field"><span>Имя</span><input name="name" required></label>'
        '<label class="rt-field"><span>Телефон</span><input name="phone" type="tel" required></label>'
        '<label class="rt-field"><span>Комментарий</span><textarea name="comment" rows="3"></textarea></label>'
        '<label class="rt-consent"><input type="checkbox" name="consent" required>'
        '<span>Согласен на обработку персональных данных</span></label>'
        '<p class="rt-note" role="status"></p>'
        '<button type="submit" class="rt-btn rt-btn--primary">Оформить</button>'
        '</form>'
    ),
    'search': (
        '<form class="rt-search" hidden>'
        '<input type="search" name="q" placeholder="Поиск по каталогу">'
        '<button type="submit" class="rt-btn rt-btn--primary">Найти</button>'
        '<ul class="rt-search__results"></ul>'
        '</form>'
    ),
}


def _render_needs_runtime(block: dict, records: list[dict] | None = None) -> str:
    """Модуль, которому нужен рантайм: заглушка и скрытый рабочий блок.

    Корзина, оформление и поиск держат состояние между страницами и
    запросами, а статический пакет бэкенда не содержит (ТЗ п.16.4,
    ADR-0005). Раньше они выводились общими функциями и выглядели
    рабочими: список товаров на месте «корзины», форма на месте
    «оформления». Нажимать было некуда, и это выглядело как ошибка
    платформы, а не как отсутствие сервера.

    Видимая часть — честная заглушка. Рабочий блок лежит рядом и
    открывается клиенту только после того, как рантайм ответил.
    """

    module_id = str(block.get('module', ''))
    module = MODULES_BY_ID.get(module_id)
    title = module.name if module else 'Модуль'
    kind = RUNTIME_KINDS.get(module_id, '')
    template = _RUNTIME_TEMPLATES.get(kind, '')
    return (
        '<section class="section section--runtime"'
        f' data-runtime="{esc(kind)}">'
        f'<h2 class="section__title">{esc(title)}</h2>'
        f'{template}'
        '<div class="rt-placeholder">'
        '<p class="data__note">Модулю нужен рантайм: он хранит состояние '
        'между страницами и запросами. Статический пакет сервера не '
        'содержит (ТЗ п.16.4).</p>'
        '<p class="data__note">Подключите рантайм на своём хостинге и '
        'укажите его в runtime.json — модуль заработает сам '
        '(ТЗ п.16.5, ADR-0005).</p>'
        '</div>'
        '</section>'
    )


def _render_order(block: dict, records: list[dict] | None = None) -> str:
    """Форма заявки.

    Не оформление заказа: оформление создаёт запись в базе, а
    статическому пакету отправлять её некуда. Форма собирает
    значения и говорит об этом прямо: собирать их под именем
    заказа значило бы обещать больше, чем есть.
    """
    heading = _own(block, 'heading', 'Заявка')
    fields = _items(block, 'fields', ['Имя', 'Телефон', 'Комментарий'])
    submit = _own(block, 'submitLabel', 'Отправить')
    policy_field = _own(block, 'policyField', 'consent')

    inputs = ''.join(
        f'<label class="field">{esc(name)}<input name="f{index}" required></label>'
        for index, name in enumerate(fields)
    )
    consent = (
        '<p class="legal consent"><label>'
        '<input type="checkbox" name="' + esc(policy_field) + '" required> '
        'Согласен на обработку персональных данных</label></p>'
        if policy_field
        else ''
    )
    return (
        '<section class="section section--order">'
        f'<h2>{esc(heading)}</h2>'
        f'<form class="form" method="post">{inputs}{consent}'
        f'<button type="submit">{esc(submit)}</button></form>'
        '<p class="data__note">Заявка сохранится на стенде заказчика, '
        'когда к пакету будет подключён рантайм.</p>'
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


def _image_tag(src: str, alt: str) -> str:
    """Тег картинки для галереи.

    Загрузка ленивая, а размеры не заданы: без них страница «прыгает»
    при загрузке, а по атрибутам alt читается текст для скринридера —
    картинка без описания молча исчезает для незрячего посетителя.
    """
    return (
        f'<img class="media__image" src="{esc(src)}" alt="{esc(alt)}" '
        'loading="lazy" decoding="async">'
    )


def _split_images(value: object) -> list[str]:
    """Список адресов из свойства блока.

    Список приходит строкой через запятую либо JSON-массивом: человек
    вставляет ссылки из буфера, а форма не должна требовать JSON.
    """
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if not isinstance(value, str):
        return []
    raw = value.strip()
    if not raw:
        return []
    if raw.startswith('['):
        try:
            import json

            parsed = json.loads(raw)
        except ValueError:
            return [raw]
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    return [part.strip() for part in raw.split(',') if part.strip()]


def _image_src(block: dict, *keys: str) -> str:
    """Адрес картинки из свойств блока.

    Именно из свойств, а не через _text: тот на отсутствующем ключе
    берёт текст блока, и вместо адреса в src попал бы обычный текст
    вроде «Текст». Адрес — это то, что человек задал руками или
    выбрал в медиатеке, поэтому и берётся только оттуда.
    """
    props = _props(block)
    for key in keys:
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _render_media(block: dict) -> str:
    """Видео и прочие медиа без файла: честная заглушка.

    Плейсхолдер виден и в редакторе, и в выгрузке: подставлять
    чужую картинку вместо заказанной нельзя.
    """
    alt = _text(block, 'alt', _text(block, 'text', 'Видео'))
    return (
        '<figure class="block block--media">'
        f'<div class="media__placeholder" role="img" aria-label="{esc(alt)}">'
        f'{esc(alt)}</div></figure>'
    )


def _render_image(block: dict) -> str:
    """Изображение: настоящий файл, если он задан, иначе заглушка.

    Загрузка ленивая, размеры не заданы: без них страница «прыгает»
    при загрузке, а по атрибуту alt читается текст для скринридера —
    картинка без описания молча исчезает для незрячего посетителя.
    """
    alt = _text(block, 'alt', _text(block, 'text', 'Изображение'))
    src = _image_src(block, 'src', 'image')
    if not src:
        return (
            '<figure class="block block--media">'
            f'<div class="media__placeholder" role="img" aria-label="{esc(alt)}">'
            f'{esc(alt)}</div></figure>'
        )
    return (
        '<figure class="block block--media">'
        f'<img class="media__image" src="{esc(src)}" alt="{esc(alt)}" '
        'loading="lazy" decoding="async"></figure>'
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
    'media.image': _render_image,
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
    'shop.card': _render_card,
    'shop.catalog': _render_catalog,
    'shop.reviews': _render_reviews,
    'shop.price': _render_price,
    'shop.compare': _render_compare,
    'shop.stock': _render_stock,
    'shop.order': _render_order,
    'promo.pricing': _render_pricing,
    'promo.banner': _render_promo_banner,
    'shop.order': _render_order,
    'shop.cart': _render_needs_runtime,
    'shop.search': _render_needs_runtime,
    'shop.checkout': _render_needs_runtime,
    'shop.compare': _render_compare,
}


#: Модули, которые вычисляют по полям: агрегат, фильтр, сортировка,
#: счётчик и связанные записи. Им нужны записи целиком, а не строки.
DATASET_MODULES = frozenset({
    'data.aggregate',
    'data.filter',
    'data.sort',
    'data.count',
    'data.related',
    'shop.catalog',
    'shop.card',
    'shop.price',
    'promo.pricing',
    'shop.compare',
    'shop.reviews',
    'shop.stock',
})


def render_block(
    block: dict,
    records: list[dict] | None = None,
    dataset: list[dict] | None = None,
) -> RenderedBlock:
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
    # Модулям, которые считают и сортируют, нужны записи по полям, а не
    # готовые строки. Список задан явно: передавать третий аргумент
    # всем нельзя — рендереры без него сломались бы, а разбирать
    # сигнатуру на лету избыточно.
    if module_id in DATASET_MODULES:
        body = renderer(block, records or [], dataset or [])
    elif needs_records:
        body = renderer(block, records or [])
    else:
        body = renderer(block)
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
  {'\n  '.join(var.rstrip().rstrip(';') + ';' for var in variables)}
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

/* Настоящие картинки. Ширина по контейнеру и высота по пропорции:
   иначе на телефоне картинка вылезает за экран, а в пустом блоке
   страница «прыгает» при загрузке. */
.media__image {{
  display: block;
  width: 100%;
  height: auto;
  border-radius: var(--radius-media);
}}

.gallery__grid {{
  display: grid;
  gap: var(--gallery-gap, 16px);
  grid-template-columns: repeat(var(--gallery-columns, 3), minmax(0, 1fr));
}}

.gallery__item {{
  margin: 0;
}}

@media (width <= 720px) {{
  .gallery__grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
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

/* Коммерческие блоки. Каждый узнаваем по классу: иначе на странице
   нельзя отличить предложение от обычной секции, а заявку от текста. */
.banner {{
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-start;
  margin: 0 0 24px;
  padding: 32px;
  border-radius: 12px;
  background: var(--fill-section);
  border: 1px solid var(--border);
}}
.banner--accent {{ background: var(--accent); color: var(--on-accent); }}
.banner--dark {{ background: #14161A; color: #F7F8F9; }}
.banner--center {{ align-items: center; text-align: center; }}
.banner--right {{ align-items: flex-end; text-align: right; }}
.banner h2 {{ margin: 0; font-size: 28px; }}
.banner p {{ margin: 0; }}
.banner__action {{
  display: inline-block;
  padding: 12px 24px;
  border-radius: 24px;
  background: var(--accent);
  color: var(--on-accent);
  text-decoration: none;
}}

.plans {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
.plan {{ border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
.plan--highlight {{ border-color: var(--accent); border-width: 2px; }}
.plan__title {{ margin: 0 0 8px; font-size: 20px; }}
.plan__price {{ margin: 0; font-size: 26px; font-weight: 700; }}
.plan__period {{ margin: 4px 0 12px; color: var(--text-muted); }}
.plan__features {{ margin: 0; padding-left: 18px; color: var(--text-muted); }}

.compare {{ width: 100%; border-collapse: collapse; }}
.compare th, .compare td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }}
.compare thead th {{ color: var(--text-muted); font-size: 14px; }}

.reviews {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }}
.review {{ border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
.review blockquote {{ margin: 0 0 8px; }}
.review figcaption {{ color: var(--text-muted); }}

.stock__value {{ font-size: 40px; font-weight: 700; margin-right: 10px; }}
.stock--low .stock__value {{ color: #8A5A00; }}
.stock--out .stock__value {{ color: var(--text-muted); }}
.stock__note {{ margin: 4px 0 0; color: var(--text-muted); font-size: 14px; }}

.form {{ display: grid; gap: 12px; max-width: 460px; }}
.field {{ display: grid; gap: 4px; }}
.field input {{ padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font: inherit; }}
.form button {{ padding: 12px 24px; border: 0; border-radius: 8px; background: var(--accent); color: var(--on-accent); font: inherit; cursor: pointer; }}
.consent {{ margin: 0; color: var(--text-muted); }}

/* Блоки корзины, оформления и поиска. Разметка лежит в статике
   всегда, но видна только после ответа рантайма. */
.rt-placeholder {{ color: var(--text-muted); }}
.rt-cart__items {{ list-style: none; margin: 0 0 12px; padding: 0; }}
.rt-cart__row {{ display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border); }}
.rt-cart__name {{ flex: 1; }}
.rt-cart__qty {{ display: inline-flex; align-items: center; gap: 8px; }}
.rt-btn {{ padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px; background: transparent; font: inherit; cursor: pointer; }}
.rt-btn--primary {{ background: var(--accent); color: var(--on-accent); border-color: transparent; }}
.rt-btn--ghost {{ padding: 4px 10px; }}
.rt-btn:disabled {{ opacity: 0.6; cursor: default; }}
.rt-form {{ display: grid; gap: 12px; max-width: 420px; }}
.rt-field {{ display: grid; gap: 4px; }}
.rt-field input, .rt-field textarea, .rt-search input {{ padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font: inherit; }}
.rt-consent {{ display: flex; gap: 8px; align-items: flex-start; color: var(--text-muted); }}
.rt-search {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.rt-search input {{ flex: 1; min-width: 200px; }}
.rt-search__results {{ list-style: none; margin: 12px 0 0; padding: 0; width: 100%; }}
.rt-search__row {{ display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border); }}
.rt-search__empty {{ color: var(--text-muted); }}
.rt-note {{ margin: 8px 0 0; color: var(--text-muted); }}
.rt-note--error {{ color: #8A1F1F; }}

/* Модуль, которому нужен рантайм: рамка пунктиром, чтобы заглушка
   читалась как «здесь будет блок», а не как готовый пустой блок. */
.section--needs-runtime {{ border: 1px dashed var(--border); }}
.section--needs-runtime h2 {{ margin: 0 0 8px; font-size: 20px; }}

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
