"""Типограф: правильные знаки в текстах страницы.

Зачем это вообще нужно. Человек набирает текст в панели свойств
обычной клавиатурой: прямые кавычки, дефис вместо тире, три точки
вместо многоточия. На сайте это выглядит как черновик — заказчик
замечает в первую очередь именно такие мелочи.

Правила сознательно консервативные. Типограф не исправляет
орфографию и не переписывает фразы: он трогает только знаки, где
однозначное правило существует. Всё спорное остаётся как есть —
испорченный смысл хуже некрасивой кавычки.

Функция обязана быть идемпотентной: повторный прогон по уже
обработанному тексту не меняет ни одного символа. Иначе каждое
сохранение страницы добавляло бы новые неразрывные пробелы.
"""

from __future__ import annotations

import re

#: Свойства, в которых лежат не тексты, а технические значения:
#: адреса, имена полей, идентификаторы, код. Типограф их не трогает —
#: замена дефиса на тире внутри URL ломает ссылку, а «умные» кавычки
#: в коде делают его нерабочим.
TECHNICAL_PROPS = frozenset({
    'href', 'src', 'url', 'link', 'buttonLink', 'image', 'images',
    'source', 'field', 'titleField', 'textField', 'ratingField',
    'priceField', 'periodField', 'featuresField', 'imageField',
    'highlightField', 'nameField', 'valueField', 'email', 'phone',
    'inn', 'ogrn', 'anchor', 'id', 'module', 'language', 'code',
    'filename', 'mime', 'slug', 'color', 'background', 'align', 'size',
    'icon', 'videoUrl', 'embed', 'mapUrl', 'utm', 'phoneHref',
})

#: Порог, после которого текст считается не прозой, а выгрузкой
#: данных: обрабатывать мегабайтную строку на каждый блок незачем.
MAX_TEXT = 20_000

_RE_MULTISPACE = re.compile(r'[ \t]{2,}')
_RE_SPACE_BEFORE_PUNCT = re.compile(r'[ \t]+([,.;:!?])')
_RE_DOUBLE_HYPHEN = re.compile(r'--+')
_RE_SPACED_HYPHEN = re.compile(r'[ \t]+-[ \t]+')
_RE_SPACED_DASH = re.compile(r'[ \t]+—[ \t]*')
#: Короткие слова, которые не должны оставаться в конце строки:
#: предлоги, союзы и частицы. Список явный, а не «любое слово из двух
#: букв»: правило для всех коротких слов цепляло бы «он», «мы», «их» —
#: обычные слова, которым неразрывный пробел не нужен и только мешает
#: переносам.
SHORT_WORDS = (
    'а', 'бы', 'в', 'во', 'до', 'же', 'за', 'и', 'из', 'к', 'ко', 'ли',
    'на', 'не', 'ни', 'но', 'о', 'об', 'от', 'по', 'с', 'со', 'то', 'у', 'я',
)
_RE_SHORT_WORD = re.compile(
    r'(?<![\w])(' + '|'.join(sorted(SHORT_WORDS, key=len, reverse=True)) + r')[ \t]+',
    re.IGNORECASE,
)
#: Число и следующая за ним единица или слово: «5 кг», «2026 год».
_RE_NUMBER_UNIT = re.compile(r'(\d)[ \t]+(?=[А-Яа-яЁёA-Za-z%₽$€])')


def smart_quotes(text: str) -> str:
    """Прямые кавычки в «ёлочки».

    Если кавычек нечётное число, текст остаётся как есть: скорее всего,
    это апостроф или незакрытая кавычка, и автоматическая расстановка
    сделала бы хуже. Вложенные кавычки не различаются — для них нужно
    понимать структуру фразы, а не считать символы.
    """

    if text.count('"') % 2:
        return text

    out: list[str] = []
    opening = True
    for char in text:
        if char == '"':
            out.append('«' if opening else '»')
            opening = not opening
        else:
            out.append(char)
    return ''.join(out)


def typograph(text: str) -> str:
    """Расставляет типографские знаки. Безопасна для повторного вызова."""

    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        return text

    result = text
    # Порядок важен: сначала убираем лишние пробелы, потом ставим
    # знаки, и только в конце — неразрывные пробелы. Иначе правило
    # коротких слов съело бы пробел перед запятой.
    result = _RE_MULTISPACE.sub(' ', result)
    result = _RE_SPACE_BEFORE_PUNCT.sub(r'\1', result)
    result = result.replace('...', '…')
    result = smart_quotes(result)
    result = _RE_DOUBLE_HYPHEN.sub('—', result)
    result = _RE_SPACED_HYPHEN.sub(' — ', result)
    result = _RE_SPACED_DASH.sub('\u00a0— ', result)
    # Замена собирается склейкой: \u00a0 внутри шаблона замены re
    # не разбирает, и запись r'\1\u00a0' даёт ошибку «bad escape \u».
    result = _RE_SHORT_WORD.sub(r'\1' + '\u00a0', result)
    result = _RE_NUMBER_UNIT.sub(r'\1' + '\u00a0', result)
    return result


def typograph_block(block: dict) -> dict:
    """Копия блока с обработанными текстами.

    Копия, а не правка на месте: дерево приходит из базы и может
    использоваться повторно (например, в нескольких страницах пакета).
    Менять его по дороге — значит получить разный результат у одной и
    той же версии в зависимости от порядка вызовов.
    """

    props = block.get('props')
    changed = False
    new_props = props
    if isinstance(props, dict):
        new_props = {}
        for key, value in props.items():
            if isinstance(value, str) and key not in TECHNICAL_PROPS:
                fixed = typograph(value)
                if fixed != value:
                    changed = True
                new_props[key] = fixed
            else:
                new_props[key] = value

    new_block = block
    for key in ('content', 'label'):
        value = block.get(key)
        if isinstance(value, str):
            fixed = typograph(value)
            if fixed != value:
                if new_block is block:
                    new_block = dict(block)
                new_block[key] = fixed
                changed = True

    if changed:
        if new_block is block:
            new_block = dict(block)
        new_block['props'] = new_props
    return new_block
