"""PWA-часть сценария 4 (ТЗ п.16.6).

Установка сайта на главный экран и работа офлайн. Файлы собираются
здесь, а не пишутся строкой в коде: service worker легко испортить
опечаткой, и такую ошибку видно только на устройстве покупателя.

Два решения, о которых стоит сказать сразу.

* Иконка — SVG, а не PNG. Генерация PNG без внешней библиотеки
  означала бы писать свой кодек; SVG с `sizes: any` и
  `type: image/svg+xml` понимают все браузеры, поддерживающие PWA,
  и он остаётся векторным на любом экране.
* Кешируется только статика. Страница с корзиной кешироваться не
  должна: человек увидел бы свой заказ из прошлого визита и решил,
  что его оформили снова.
"""

from __future__ import annotations

import json

#: Версия формата манифеста. Отдельная от версии протокола
#: рантайма: манифест читает браузер, а не наш код.
WEB_MANIFEST_VERSION = 1


def icon_svg(name: str, background: str, foreground: str) -> str:
    """Иконка приложения.

    Текст в SVG — это текст в системном шрифте: он не требует
    подключения шрифта и потому не тянет за собой лицензию и сеть.
    """
    initial = (name.strip() or 'A')[0].upper()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="{_escape(initial)}">
  <rect width="512" height="512" rx="96" fill="{background}"/>
  <text x="256" y="336" font-family="system-ui, sans-serif" font-size="256"
        font-weight="700" fill="{foreground}" text-anchor="middle">{_escape(initial)}</text>
</svg>
"""


def _escape(value: str) -> str:
    return (
        str(value)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def manifest(name: str, start_url: str, theme_color: str,
             background_color: str) -> str:
    """Манифест веб-приложения (ТЗ п.16.6)."""
    payload = {
        'name': name,
        'short_name': name[:12],
        'start_url': start_url,
        'scope': '/',
        'display': 'standalone',
        'background_color': background_color,
        'theme_color': theme_color,
        'lang': 'ru',
        'dir': 'ltr',
        'icons': [
            {
                'src': 'assets/icons/icon.svg',
                'sizes': 'any',
                'type': 'image/svg+xml',
                'purpose': 'any',
            },
            {
                'src': 'assets/icons/icon-maskable.svg',
                'sizes': 'any',
                'type': 'image/svg+xml',
                'purpose': 'maskable',
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def maskable_icon(name: str, background: str, foreground: str) -> str:
    """Иконка для maskable: с безопасной зоной.

    Android обрезает края по форме системы, и рисунок без запаса
    обрезался бы по буквам.
    """
    initial = (name.strip() or 'A')[0].upper()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="{_escape(initial)}">
  <rect width="512" height="512" fill="{background}"/>
  <text x="256" y="320" font-family="system-ui, sans-serif" font-size="176"
        font-weight="700" fill="{foreground}" text-anchor="middle">{_escape(initial)}</text>
</svg>
"""


def registration_script() -> str:
    """Регистрация worker файлом, а не строкой в HTML.

    Отдельный файл вместо инлайнового скрипта: страница остаётся
    пригодной для строгой политики безопасности, где инлайновые
    скрипты запрещены, а установка приложения без регистрации
    просто не работает.
    """
    return """/* Регистрация service worker (сценарий 4, ТЗ п.16.6). */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('service-worker.js').catch(function () {
      /* Сайт работает и без worker: офлайн просто не будет. */
    });
  });
}
"""


def service_worker(version: int, precache: list[str]) -> str:
    """Service worker: офлайн для статики, свежесть — при появлении сети.

    Имена файлов в списке — из пакета, а не «просто всё в assets»:
    в precache попадает только то, что точно нужно для первого
    открытия офлайн.
    """
    entries = '\n'.join(f"        {json.dumps(name)}," for name in precache)
    return f"""/* Service worker проекта. Собран автоматически, руками не правится.
 *
 * Стратегия: статика отдаётся из кеша и одновременно обновляется по
 * сети. Пользователь видит сайт мгновенно и получает свежую версию
 * при следующем открытии — в отличие от «сначала сеть», где офлайн
 * означает пустую страницу.
 *
 * Кешируются только файлы сборки. Документы и всё, что меняется
 * по запросу, идут в сеть: иначе покупатель увидел бы свой старый
 * заказ как действующий.
 */
'use strict';

const VERSION = {json.dumps(f'v{version}')};
const CACHE = 'aurabuilder-' + VERSION;
const PRECACHE = [
{entries}
];

self.addEventListener('install', (event) => {{
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
}});

self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith('aurabuilder-') && key !== CACHE)
            .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
}});

function isCacheable(request) {{
  if (request.method !== 'GET') return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith('/api/')) return false;
  return PRECACHE.some((name) => name === 'assets/' + url.pathname.split('/').pop());
}}

self.addEventListener('fetch', (event) => {{
  const {{ request }} = event;
  if (!isCacheable(request)) return;

  event.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(request).then((cached) => {{
        const network = fetch(request).then((response) => {{
          if (response && response.ok) cache.put(request, response.clone());
          return response;
        }}).catch(() => cached);
        return cached || network;
      }})
    )
  );
}});
"""