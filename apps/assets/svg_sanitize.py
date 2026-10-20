"""Санитайзер SVG: опасное не пропускается, лишнее вырезается.

Раньше здесь был отказ по подстроке: искались `<script>`, обработчики
событий и `javascript:`. Такое проверка обходится, и это видно даже без
пентеста: `<foreignObject>` с HTML, `<use href="data:...">`, `style` с
`behavior`, `<a xlink:href="...">` — все они попадают на страницу
заказчика. Поэтому опасное не отлавливается по шаблону, а вырезается.

Два разных ответа, потому что причины у них разные:

* Опасное содержимое — отказ. Скрипт или внешняя ссылка в картинке
  означают, что автор что-то имел в виду, и молча вырезать это значит
  отдать владельцу картинку, которая не делает того, чего он ждёт.
* Неподдерживаемое, но безопасное — зачистка. Анимация или неизвестный
  элемент не опасны, и картинка должна остаться картинкой.

SVG раздаётся и прямо по адресу медиатеки: браузер открывает его как
документ и исполняет скрипты внутри него. Поэтому проверка нужна именно
на записи, а не на показе.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

#: Элементы, из которых состоит рисунок. Всё, чего здесь нет, —
#: вырезается: `<script>`, `<foreignObject>`, `<iframe>` и им подобные
#: не являются частью картинки, а являются способом выполнить код.
SAFE_ELEMENTS = frozenset({
    'svg', 'g', 'defs', 'desc', 'title',
    'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
    'text', 'tspan', 'textPath',
    'linearGradient', 'radialGradient', 'stop',
    'clipPath', 'mask', 'pattern',
    'image', 'use', 'marker', 'style',
})

#: Элементы, которые исполняют код или тянут чужое. Их присутствие —
#: отказ, а не зачистка: владелец ждёт от картинки действия, и молча
#: вырезать его значит обмануть.
DANGEROUS_ELEMENTS = frozenset({
    'script', 'foreignobject', 'iframe', 'embed', 'object', 'applet',
    'audio', 'video', 'canvas', 'meta', 'link', 'base', 'form', 'input',
    'button', 'select', 'textarea', 'option', 'frame', 'frameset',
    'handler', 'listener', 'a', 'animation',
})

#: Атрибуты, которые не могут повлиять на выполнение кода. Обработчики
#: событий (`onload`, `onclick`, …) начинаются с `on` — они запрещены
#: целиком и здесь не перечисляются.
SAFE_ATTRIBUTES = frozenset({
    # Раскладка и форма
    'x', 'y', 'width', 'height', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r',
    'rx', 'ry', 'd', 'points', 'pathLength', 'preserveAspectRatio', 'viewBox',
    # Оформление
    'fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width',
    'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray',
    'stroke-dashoffset', 'stroke-opacity', 'stroke-miterlimit', 'opacity',
    'color', 'display', 'visibility', 'overflow', 'clip', 'clip-rule',
    # Трансформации
    'transform', 'gradientTransform', 'patternTransform',
    'gradientUnits', 'patternUnits', 'patternContentUnits', 'maskUnits',
    'maskContentUnits', 'clipPathUnits', 'spreadMethod', 'markerWidth',
    'markerHeight', 'markerUnits', 'orient', 'refX', 'refY', 'marker-start',
    'marker-mid', 'marker-end',
    # Текст
    'font-family', 'font-size', 'font-weight', 'font-style', 'text-anchor',
    'dominant-baseline', 'alignment-baseline', 'letter-spacing',
    'word-spacing', 'text-decoration', 'writing-mode', 'startOffset',
    'method', 'spacing', 'textLength', 'lengthAdjust', 'side', 'glyphRef',
    # Градиенты
    'offset', 'stop-color', 'stop-opacity', 'fx', 'fy',
    # Ссылка внутри файла и служебные поля
    'href', 'xlink:href', 'id', 'class', 'style',
})

#: Тот же список в нижнем регистре: сравнение идёт по имени без
#: пространства имён, и регистр для XML не имеет значения.
_SAFE_ATTRIBUTES = frozenset(name.lower() for name in SAFE_ATTRIBUTES)

#: Свойства CSS, которые задают только внешний вид. Всё, что может
#: загрузить адрес или выполнить код (`url()`, `behavior`, `expression()`),
#: сюда не попадает.
SAFE_CSS_PROPERTIES = frozenset({
    'color', 'opacity', 'fill', 'fill-opacity', 'fill-rule', 'stroke',
    'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray',
    'stroke-dashoffset', 'stroke-opacity', 'stroke-miterlimit', 'font-family',
    'font-size', 'font-weight', 'font-style', 'font-variant', 'text-anchor',
    'text-decoration', 'letter-spacing', 'word-spacing', 'dominant-baseline',
    'alignment-baseline', 'writing-mode', 'display', 'visibility',
})

#: Значения CSS, которые грузят чужое или исполняют код.
CSS_FORBIDDEN = re.compile(
    r'url\s*\(|behavior\s*:|expression\s*\(|@import|javascript\s*:|vbscript\s*:'
    r'|-moz-binding|data\s*:',
    re.IGNORECASE,
)

#: Ссылка внутри самого файла. Внешние адреса в картинке недопустимы:
#: она бы сообщала владельцу сервера, что адрес открыли, и тянула бы
#: чужие файлы.
SAFE_HREF = re.compile(r'^#[A-Za-z0-9_.:-]+$')


class SvgUnsafe(ValueError):
    """SVG нельзя принять как картинку. Текст идёт пользователю."""


def _local_name(tag: str) -> str:
    """Имя элемента без пространства имён.

    В SVG элементы приходят как `{http://www.w3.org/2000/svg}path` после
    разбора: само пространство имён безопасно, но в разрешённый список
    оно попасть не должно.
    """
    if tag.startswith('{'):
        return tag.split('}', 1)[-1]
    return tag


def _clean_style(value: str) -> str:
    """CSS из атрибута style: только безопасные свойства.

    Строка делится по точке с запятой, и каждое объявление остаётся,
    если его имя разрешено. Так вырезается и `url(...)`, и подстановка
    через `behavior`, не читая их как CSS.
    """
    parts: list[str] = []
    for declaration in value.split(';'):
        if not declaration.strip():
            continue
        name = declaration.split(':', 1)[0].strip().lower()
        if name in SAFE_CSS_PROPERTIES:
            parts.append(declaration.strip())
    return '; '.join(parts)


def _clean_css_text(text: str) -> str:
    """CSS внутри `<style>`: безопасные объявления и ничего лишнего.

    Стиль умеет грузить чужое через `url()` и подключать скрипт через
    `behavior`, поэтому сначала проверяется запрет, а потом из каждого
    правила остаются только разрешённые свойства.
    """
    if CSS_FORBIDDEN.search(text):
        raise SvgUnsafe(
            'в SVG найден стиль, который грузит чужое или исполняет код'
        )
    kept: list[str] = []
    for rule in text.split('}'):
        rule = rule.strip()
        if not rule or '{' not in rule:
            continue
        selector, declarations = rule.split('{', 1)
        parts = [
            d.strip() for d in declarations.split(';')
            if d.strip() and d.split(':', 1)[0].strip().lower() in SAFE_CSS_PROPERTIES
        ]
        if parts:
            kept.append(f'{selector.strip()} {{ {" ".join(parts)}; }}')
    return '\n'.join(kept)


def _clean_href(value: str) -> str | None:
    """Адрес внутри файла или None, если ссылаться нельзя.

    `data:` опасен: им можно вставить страницу внутрь картинки, а вместе
    с ней — скрипт. Внешний адрес тоже недопустим: картинка обязана
    работать без сети и не должна ничего сообщать о себе.
    """
    href = (value or '').strip()
    if SAFE_HREF.match(href):
        return href
    return None


def sanitize_svg(content: bytes) -> bytes:
    """Возвращает SVG, из которого убрано всё лишнее.

    Опасное содержимое — отказ: скрипт, обработчик события, внешняя ссылка.
    Неподдерживаемое, но безопасное — вырезано, и картинка остаётся
    картинкой. Отказ по неразбираемому файлу или чужому формату: это
    уже не картинка, и называть её так незачем.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SvgUnsafe(f'SVG не разбирается как XML: {exc}') from exc

    if _local_name(root.tag) != 'svg':
        raise SvgUnsafe('корневой элемент не <svg>: это не векторная картинка')

    _clean_node(root)

    # Комментарии вырезаются: в них удобно прятать начало элемента, а
    # сам комментарий в картинке ничего не значит.
    for node in list(root.iter()):
        if node.tag is ET.Comment:
            root.remove(node)

    return ET.tostring(root, encoding='utf-8', xml_declaration=False)


def _clean_node(node: ET.Element) -> None:
    """Чистит элемент и его поддерево, отказывая в опасном.

    Имена сравниваются в нижнем регистре и без пространства имён:
    в XML регистр значения не имеет, а пространство имён — способ
    назвать тот же самый `href` по-другому, и без этого проверка
    пропускала `xlink:href`.
    """
    for child in list(node):
        name = _local_name(child.tag).lower()
        if name in DANGEROUS_ELEMENTS:
            raise SvgUnsafe(
                f'в SVG найден элемент <{name}>: он исполняет код или '
                'загружает чужое. Уберите его и загрузите снова.'
            )
        if name not in SAFE_ELEMENTS:
            # Неподдерживаемый, но безопасный элемент: вырезается вместе
            # с содержимым, иначе браузер дорисовал бы его по-своему.
            node.remove(child)
            continue
        _clean_node(child)

    for name in list(node.attrib):
        local = _local_name(name).lower()
        if local.startswith('on'):
            raise SvgUnsafe(
                f'в SVG найден обработчик событий «{name}»: он исполняет '
                'код на странице. Уберите его и загрузите снова.'
            )
        if local not in _SAFE_ATTRIBUTES:
            del node.attrib[name]
            continue
        value = node.attrib[name]
        if local == 'style':
            cleaned = _clean_style(value)
            if cleaned:
                node.attrib[name] = cleaned
            else:
                del node.attrib[name]
        elif local in ('href', 'xlink:href'):
            href = _clean_href(value)
            if href is None:
                raise SvgUnsafe(
                    f'в SVG найдена внешняя ссылка «{value[:60]}»: картинка '
                    'не должна ничего грузить со стороны. Уберите её и '
                    'загрузите снова.'
                )
            node.attrib[name] = href

    # CSS внутри <style> — тоже содержимое, и он должен пройти ту же
    # проверку, что атрибут style: стиль умеет грузить чужое через url().
    if _local_name(node.tag).lower() == 'style':
        node.text = _clean_css_text(node.text or '')


__all__ = [
    'DANGEROUS_ELEMENTS',
    'SAFE_ATTRIBUTES',
    'SAFE_ELEMENTS',
    'SvgUnsafe',
    'sanitize_svg',
]