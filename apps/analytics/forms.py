"""Приём заявок с форм опубликованного сайта.

Заявка приходит от анонимного посетителя, поэтому доверять в ней
ничего нельзя. Но и потерять её нельзя: чаще всего это единственный
контакт, который человек оставил. Отсюда правила: ограничить размер,
не хранить ничего кроме полей формы и не превращать мусор в отказ —
если заявка не похожа на заявку, отвечаем отказом, а не пишем пустую
строку.

Сайт определяется по адресу страницы, с которой пришла форма
(Referer). Явное поле `_site` оставлено для случаев, когда реферера
нет: некоторые браузеры и расширения его вырезают.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

#: Верхние границы заявки. Форма — это контакты и короткий текст, а не
#: файл: 32 КБ хватает с запасом, а всё большое отсекается до записи.
MAX_FORM_BYTES = 32 * 1024
MAX_FORM_FIELDS = 40
MAX_FIELD_NAME = 80
MAX_FIELD_VALUE = 2000

SITE_PATH_RE = re.compile(r'^/sites/(?P<slug>[a-z0-9-]+)(?P<rest>/.*)?$')


def _normalise_page(path: str) -> str:
    page = '/' + (path or '').lstrip('/')
    if page.endswith('/index.html'):
        page = page[:-len('index.html')]
    return page or '/'


def page_from_referer(referer: str, slug: str) -> str:
    """Страница, с которой отправлена форма."""
    parsed = urlparse(referer or '')
    path = parsed.path or '/'
    prefix = f'/sites/{slug}'
    if path == prefix or path.startswith(prefix + '/'):
        path = path[len(prefix):] or '/'
    return _normalise_page(path)[:200]


def site_slug_from_referer(referer: str) -> str:
    parsed = urlparse(referer or '')
    match = SITE_PATH_RE.match(parsed.path or '')
    if match:
        return match.group('slug')
    # В эксплуатации сайт живёт на поддомене: shop.example.ru →
    # shop. Первая метка хоста — единственное, за что можно
    # зацепиться, не зная домена платформы.
    return (parsed.hostname or '').split('.')[0].lower()


def utm_from_referer(referer: str) -> str:
    query = parse_qs(urlparse(referer or '').query)
    return (query.get('utm_source') or [''])[0]


def clean_fields(data: dict) -> dict:
    """Оставляет только простые поля и обрезает слишком длинные.

    Служебные ключи (`_site`, `_hp`) не сохраняются: это не данные
    человека. Вложенные объекты тоже отбрасываются — форма не умеет
    их присылать, а хранить произвольную структуру незачем.
    """
    fields: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or key.startswith('_'):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            value = str(value)
        elif not isinstance(value, str):
            continue
        value = value.strip()
        if not value:
            continue
        name = key.strip()[:MAX_FIELD_NAME]
        if not name:
            continue
        fields[name] = value[:MAX_FIELD_VALUE]
        if len(fields) >= MAX_FORM_FIELDS:
            break
    return fields


__all__ = [
    'MAX_FIELD_NAME',
    'MAX_FIELD_VALUE',
    'MAX_FORM_BYTES',
    'MAX_FORM_FIELDS',
    'clean_fields',
    'page_from_referer',
    'site_slug_from_referer',
    'utm_from_referer',
]
