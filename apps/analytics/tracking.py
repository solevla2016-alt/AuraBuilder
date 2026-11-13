"""Подсчёт просмотров при раздаче опубликованного сайта.

Счётчик стоит на сервере, а не в скрипте на странице. Так пакет
остаётся статическим (ТЗ п.16.4), посетителю не ставится ни одного
cookie, а блокировщики рекламы не могут «съесть» статистику. Цена
решения: просмотры видны только у сайтов, которые раздаёт платформа;
у копии, положенной на чужой хостинг, счётчика нет — и это честно,
потому что платформа о такой копии ничего не знает.

Считаются только HTML-страницы и только GET. Картинки, стили и
скрипты — не просмотры: иначе одна страница давала бы десяток
«визитов». Роботы отбрасываются по User-Agent: поисковый обход не
должен выглядеть как интерес людей.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import PageView, TrafficSource

logger = logging.getLogger(__name__)

#: Сколько дней хранятся суточные суммы. Просмотры — не бухгалтерия:
#: год истории достаточно, чтобы увидеть сезонность, а дальше таблица
#: только растёт.
KEEP_DAYS = 400

#: Признаки робота в User-Agent. Список намеренно короткий и по
#: подстрокам: он отсекает массовый обход, а не изображает точную
#: классификацию клиентов.
BOT_MARKERS = (
    'bot', 'crawler', 'spider', 'preview', 'curl', 'wget',
    'python-requests', 'headless', 'lighthouse', 'monitoring',
)

SEARCH_HOSTS = (
    'yandex.ru', 'ya.ru', 'google.com', 'google.ru', 'bing.com',
    'duckduckgo.com', 'mail.ru', 'rambler.ru', 'sm.cn', 'baidu.com',
)

SOCIAL_HOSTS = (
    'vk.com', 't.me', 'telegram.org', 'ok.ru', 'facebook.com',
    'instagram.com', 'youtube.com', 'youtu.be', 'x.com', 'twitter.com',
    'dzen.ru', 'zen.yandex.ru', 'pinterest.com', 'reddit.com',
)

#: Источник в базе ограничен 60 символами. Всё, что не буква, цифра,
#: точка, дефис или подчёркивание, заменяется дефисом: иначе в отчёт
#: попал бы кусок URL с параметрами.
SOURCE_JUNK = re.compile(r'[^0-9a-zа-я._-]+')


def is_bot(user_agent: str) -> bool:
    agent = (user_agent or '').lower()
    return any(marker in agent for marker in BOT_MARKERS)


def normalize_page(relative: str) -> str:
    """Путь страницы в виде, пригодном для отчёта.

    `index.html` — это корень или раздел, а не отдельная страница:
    иначе «/» и «/index.html» считались бы двумя разными адресами.
    """
    path = '/' + (relative or '').replace('\\', '/').lstrip('/')
    if path.endswith('/index.html'):
        path = path[:-len('index.html')]
    if not path:
        path = '/'
    return path[:200]


def _clean_source(value: str) -> str:
    cleaned = SOURCE_JUNK.sub('-', (value or '').strip().lower()).strip('-')
    return cleaned[:60]


def _host(value: str) -> str:
    try:
        return (urlparse(value).hostname or '').lower()
    except ValueError:
        return ''


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def traffic_source(referer: str, own_host: str, utm: str = '') -> str:
    """Источник перехода: utm_source, домен реферера или direct.

    Порядок важен. UTM — это явное указание владельца ссылки, и оно
    точнее догадки по домену. Реферер с того же сайта — внутренний
    переход, а не новый посетитель из поиска.
    """
    utm_source = _clean_source(utm)
    if utm_source:
        return utm_source

    host = _host(referer)
    if not host:
        return 'direct'

    own = _host(f'//{own_host}') if own_host else ''
    if own and host == own:
        return 'internal'
    if _matches(host, SOCIAL_HOSTS):
        return 'social'
    if _matches(host, SEARCH_HOSTS):
        return 'search'
    return host.removeprefix('www.')[:60] or 'direct'


def source_of(request) -> str:
    referer = request.META.get('HTTP_REFERER', '')
    utm = request.GET.get('utm_source', '')
    if not utm and referer:
        utm = (parse_qs(urlparse(referer).query).get('utm_source') or [''])[0]
    return traffic_source(referer, request.get_host(), utm)


def _bump(model, *, site, day: date, key: str, value: str) -> None:
    """Увеличивает счётчик на единицу, создавая строку при первом визите.

    update() вместо чтения-записи: два одновременных посетителя не
    должны затирать счёт друг друга. Гонка на создании строки
    обрабатывается повтором — она возможна только в первый визит за
    день, а терять её из-за исключения нельзя.
    """
    lookup = {'site': site, 'day': day, key: value}
    updated = model.objects.filter(**lookup).update(views=F('views') + 1)
    if updated:
        return
    try:
        with transaction.atomic():
            model.objects.create(views=1, **lookup)
    except IntegrityError:
        model.objects.filter(**lookup).update(views=F('views') + 1)


def _prune(site_id) -> None:
    """Удаляет старые суммы не чаще раза в сутки на сайт.

    Проверка через кеш, а не по каждой записи: DELETE на каждый
    просмотр был бы дороже самого учёта. Если кеш недоступен, ошибку
    проглатываем — статистика не должна ломать раздачу сайта.
    """
    today = timezone.localdate()
    key = f'analytics:pruned:{site_id}:{today.isoformat()}'
    if cache.get(key):
        return
    cutoff = today - timedelta(days=KEEP_DAYS)
    PageView.objects.filter(site_id=site_id, day__lt=cutoff).delete()
    TrafficSource.objects.filter(site_id=site_id, day__lt=cutoff).delete()
    cache.set(key, True, 60 * 60 * 24)


def note_view(site, site_version, request, target) -> None:
    """Записывает просмотр страницы. Ошибки не влияют на ответ."""
    try:
        if request.method != 'GET':
            return
        if target.suffix.lower() not in ('.html', '.htm'):
            return
        if is_bot(request.META.get('HTTP_USER_AGENT', '')):
            return

        relative = target.resolve().relative_to(site_version.directory.resolve())
        page = normalize_page(str(relative))
        day = timezone.localdate()

        _bump(PageView, site=site, day=day, key='path', value=page)
        _bump(
            TrafficSource,
            site=site, day=day, key='source', value=source_of(request),
        )
        _prune(site.pk)
    except Exception:  # noqa: BLE001 — счётчик не имеет права ломать раздачу
        logger.exception('не удалось учесть просмотр сайта %s', site.pk)


__all__ = [
    'BOT_MARKERS',
    'KEEP_DAYS',
    'SEARCH_HOSTS',
    'SOCIAL_HOSTS',
    'is_bot',
    'normalize_page',
    'note_view',
    'source_of',
    'traffic_source',
]
