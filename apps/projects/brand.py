"""Брендбук проекта: стиль, который применяется ко всему сайту.

Зачем отдельно от библиотеки компонентов. Библиотека отвечает на
вопрос «как выглядит секция, текст и медиа». Брендбук — на вопрос
«какой у проекта фирменный цвет, шрифт, подпись и метки». Это разные
уровни: стиль вида компонента меняется редко и точечно, а акцент и
подпись — принадлежность проекта, они одинаковы на всех страницах и
во всех блоках.

Настройки хранятся словарём в Project.brand — по той же причине, что
и токены компонентов: список столбцов означал бы миграцию на каждое
новое поле. Проверка значений живёт здесь, чтобы API и сборка пакета
пользовались одним и тем же правилом.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from component_library.contrast import contrast_ratio

#: Шрифты без внешних файлов: пакет обязан открываться офлайн
#: (ТЗ п.16.4), поэтому вместо загрузки шрифта с CDN перечисляем
#: системные семейства. Inter стоит первым: если он установлен у
#: посетителя, сайт выглядит так же, как в редакторе.
FONT_STACKS: dict[str, str] = {
    'sans': "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    'system': "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",
    'serif': "Georgia, 'Times New Roman', 'PT Serif', serif",
    'mono': "'JetBrains Mono', 'SF Mono', Consolas, 'Courier New', monospace",
}

FONT_LABELS: dict[str, str] = {
    'sans': 'Inter / системный',
    'system': 'Системный',
    'serif': 'С засечками',
    'mono': 'Моноширинный',
}

#: Значения по умолчанию: пустой брендбук не меняет внешний вид уже
#: собранных сайтов — ровно то же правило, что у библиотеки компонентов.
DEFAULT_BRAND: dict[str, str] = {
    'accent': '',
    'font': 'sans',
    'signature': '',
    'utmSource': '',
    'utmMedium': '',
    'utmCampaign': '',
}

MAX_SIGNATURE = 300
MAX_UTM = 80

_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
#: В метках разрешены только символы, которые не нужно экранировать в
#: адресе. Кириллицу пользователь может написать — она закодируется при
#: подстановке, но пробелы и кавычки в метке не нужны.
_UTM = re.compile(r'^[A-Za-zА-Яа-яЁё0-9_.~-]*$')

#: Цвет текста на акценте выбирается из двух: оба проходят WCAG AA при
#: любом фоне, и промежуточные оттенки серого тут только навредили бы.
_ON_ACCENT = ('#FFFFFF', '#111827')


def normalize_brand(raw: Any) -> dict[str, str]:
    """Приводит значение из базы или запроса к полному набору полей."""

    brand = dict(DEFAULT_BRAND)
    if not isinstance(raw, dict):
        return brand
    for key in DEFAULT_BRAND:
        value = raw.get(key)
        if isinstance(value, str):
            brand[key] = value.strip()
    if brand['accent']:
        brand['accent'] = brand['accent'].upper()
    # Значение может прийти не только из API: поле правили руками или
    # старым клиентом. Неверный цвет заменяется пустым, а не попадает в
    # CSS как есть — иначе одна строка в базе ломала бы стили сайта.
    if not _HEX.match(brand['accent']):
        brand['accent'] = ''
    if brand['font'] not in FONT_STACKS:
        brand['font'] = DEFAULT_BRAND['font']
    return brand


def brand_error(raw: Any) -> str | None:
    """Текст первой ошибки или None, если брендбук корректен."""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        return 'brand: ожидается объект'
    unknown = set(raw) - set(DEFAULT_BRAND)
    if unknown:
        return f'brand: неизвестные поля {", ".join(sorted(unknown))}'
    accent = raw.get('accent')
    if accent not in (None, '') and (not isinstance(accent, str) or not _HEX.match(accent)):
        return 'brand.accent: нужен цвет вида #RRGGBB'
    font = raw.get('font')
    if font not in (None, '') and font not in FONT_STACKS:
        return f'brand.font: допустимо {", ".join(FONT_STACKS)}'
    signature = raw.get('signature')
    if signature is not None:
        if not isinstance(signature, str):
            return 'brand.signature: ожидается строка'
        if len(signature) > MAX_SIGNATURE:
            return f'brand.signature: не длиннее {MAX_SIGNATURE} символов'
    for key in ('utmSource', 'utmMedium', 'utmCampaign'):
        value = raw.get(key)
        if value in (None, ''):
            continue
        if not isinstance(value, str):
            return f'brand.{key}: ожидается строка'
        if len(value) > MAX_UTM or not _UTM.match(value):
            return (
                f'brand.{key}: до {MAX_UTM} символов, '
                'латиница, кириллица, цифры, _ . ~ -'
            )
    return None


def font_stack(brand: dict[str, str]) -> str:
    return FONT_STACKS.get(brand.get('font', ''), FONT_STACKS['sans'])


def on_accent(accent: str) -> str:
    """Самый контрастный цвет текста для выбранного фона."""

    if not accent or not _HEX.match(accent):
        return '#111827'
    return max(_ON_ACCENT, key=lambda color: contrast_ratio(color, accent))


def utm_params(brand: dict[str, str]) -> list[tuple[str, str]]:
    """Пары utm_* из брендбука, готовые к подстановке в адрес."""

    params: list[tuple[str, str]] = []
    for key, name in (
        ('utmSource', 'utm_source'),
        ('utmMedium', 'utm_medium'),
        ('utmCampaign', 'utm_campaign'),
    ):
        value = brand.get(key, '').strip()
        if value:
            params.append((name, value))
    return params


_LINK = re.compile(r'href="(https?://[^"]*)"')


def add_utm(html: str, brand: dict[str, str], own_prefix: str = '') -> str:
    """Добавляет UTM-метки к внешним ссылкам страницы.

    Трогаем только абсолютные адреса: внутренние ссылки пакета
    относительные, и метки им не нужны — иначе переходы между
    страницами одного сайта попадали бы в отчёты как внешний трафик.

    Ссылки, у которых метки уже есть, остаются как есть: человек мог
    поставить свои значения вручную, и перезаписывать их нельзя.
    """

    params = utm_params(brand)
    if not params or not html:
        return html

    suffix = '&amp;'.join(f'{name}={quote(value, safe="")}' for name, value in params)
    own = own_prefix.rstrip('/')

    def replace(match: re.Match[str]) -> str:
        url = match.group(1)
        if own and url.startswith(own):
            return match.group(0)
        if 'utm_' in url:
            return match.group(0)
        base, hash_mark, fragment = url.partition('#')
        joiner = '&amp;' if '?' in base else '?'
        return f'href="{base}{joiner}{suffix}{hash_mark}{fragment}"'

    return _LINK.sub(replace, html)
