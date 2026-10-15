"""Публичная страница Mini App: облегчённый интерфейс (ТЗ п.16.6).

Страница отдаётся без сборки и без внешних скриптов. Скрипт Telegram
(`telegram-web-app.js`) в приложении Telegram подставляет сам: объект
`window.Telegram.WebApp` доступен всегда, когда приложение открыто из
клиента, и отсутствует в обычном браузере — страница проверяет это и
ведёт себя соответственно.

Интерфейс облегчённый намеренно: внутри мессенджера полноценный
редактор с холстом, слоями и историей не нужен и не помещается. Здесь
показывается витрина проекта и кнопки, родные для Telegram.
"""

from __future__ import annotations

import html
import json

from django.http import HttpResponse

from projects.models import DocumentVersion

from .models import TelegramBot

#: Шаблон собирается здесь строкой: единственная страница приложения,
#: файл шаблона рядом с логикой читался бы как часть кода, а живым
#: он остаётся на стыке: HTML, тема Telegram и данные проекта.
PAGE = """<!DOCTYPE html>
<html lang="ru" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {{
    --bg: #ffffff; --fg: #0f0f0f; --muted: #707579; --accent: #3390ec;
    --card: #f2f3f5; --border: rgba(0,0,0,.08);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #17212b; --fg: #f5f5f5; --muted: #8d969c;
             --card: #0e1621; --border: rgba(255,255,255,.08); }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
    padding-bottom: env(safe-area-inset-bottom); }}
  header {{ padding: 12px 16px 8px; font-weight: 600; font-size: 17px; }}
  main {{ padding: 8px 16px 24px; }}
  .card {{ background: var(--card); border-radius: 12px; padding: 12px 14px;
    margin-bottom: 10px; }}
  .muted {{ color: var(--muted); font-size: 13px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 0 0 6px; }}
  p {{ margin: 0 0 8px; white-space: pre-wrap; }}
  a {{ color: var(--accent); }}
  .status {{ position: sticky; bottom: 0; padding: 10px 16px;
    border-top: 1px solid var(--border); background: var(--bg);
    font-size: 13px; color: var(--muted); }}
  .ok {{ color: #2eab61; }} .bad {{ color: #e53935; }}
</style>
</head>
<body>
<header>{header}</header>
<main>{content}</main>
<div class="status" id="status">{status}</div>
<script>
/*
 * Тема Telegram применяется к CSS-переменным: собственная тёмная тема
 * страницы иначе спорила бы с темой клиента, и в тёмном Telegram
 * приложение оставалось бы белым пятном.
 */
(function () {{
  const tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) return;
  tg.ready();
  tg.expand();
  const apply = () => {{
    const p = tg.themeParams || {{}};
    const dark = p.theme_color && p.theme_color !== 'light';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    const root = document.documentElement.style;
    if (p.bg_color) root.setProperty('--bg', p.bg_color);
    if (p.text_color) root.setProperty('--fg', p.text_color);
    if (p.hint_color) root.setProperty('--muted', p.hint_color);
    if (p.button_color) root.setProperty('--accent', p.button_color);
    if (p.secondary_bg_color) root.setProperty('--card', p.secondary_bg_color);
    tg.onEvent('themeChanged', apply);
  }};
  apply();

  // Главная кнопка Telegram ведёт на опубликованный сайт, если он есть:
  // в мессенджере это естественное продолжение, а не ещё одна кнопка.
  const url = {site_url};
  if (url) {{
    tg.MainButton.setText('Открыть сайт');
    tg.MainButton.show();
    tg.onEvent('mainButtonClicked', () => {{
      tg.openLink(url);
      tg.close();
    }});
  }}

  // Подпись initData проверяется на сервере: на клиенте она ничего
  // не доказывает, клиент получает эти данные от кого угодно.
  if (!tg.initData) {{
    document.getElementById('status').textContent =
      'Открыто в браузере: проверка Telegram не выполнялась.';
    return;
  }}
  fetch({auth_url}, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ bot: {bot}, initData: tg.initData }}),
  }})
    .then((r) => r.json().then((body) => ({{ ok: r.ok, body }})))
    .then(({{ ok, body }}) => {{
      const status = document.getElementById('status');
      if (!ok) {{
        status.innerHTML = '<span class="bad">Telegram: ' +
          (body.detail || 'данные не приняты') + '</span>';
        return;
      }}
      status.innerHTML = 'Telegram подтвердил: <span class="ok">' +
        (body.user ? body.user.displayName : '') + '</span>';
      if (tg.BackButton) tg.BackButton.show();
    }})
    .catch((e) => {{
      document.getElementById('status').innerHTML =
        '<span class="bad">Проверка не выполнена: ' + e.message + '</span>';
    }});
}})();
</script>
</body>
</html>
"""


def _latest_version(project) -> DocumentVersion | None:
    return project.versions.order_by('-number').first()


def _blocks_of(version: DocumentVersion | None) -> list[dict]:
    tree = version.tree if version and isinstance(version.tree, dict) else {}
    blocks = tree.get('blocks')
    return [b for b in blocks if isinstance(b, dict)] if isinstance(
        blocks, list) else []


def _render_text(props: dict) -> str:
    """Текст блока: заголовки, абзацы и цена товара."""
    parts = []
    for key in ('title', 'heading', 'text', 'label', 'description', 'name',
                'price'):
        value = props.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            parts.append(html.escape(str(value)))
    return ' · '.join(parts[:3])


def render(project, bot: TelegramBot, site_url: str = '') -> str:
    """Собирает страницу Mini App."""
    version = _latest_version(project)
    blocks = _blocks_of(version)

    cards: list[str] = []
    if not blocks:
        cards.append(
            '<div class="card"><p class="muted">Проект пока пуст. '
            'Соберите страницу в редакторе — она появится здесь сразу.'
            '</p></div>'
        )
    for block in blocks[:12]:
        props = block.get('props') if isinstance(block.get('props'), dict) else {}
        text = _render_text(props)
        module = html.escape(str(block.get('module') or ''))
        if not text:
            continue
        cards.append(
            f'<div class="card"><h2>{text}</h2>'
            f'<p class="muted">{module}</p></div>'
        )

    if not cards:
        cards.append(
            '<div class="card"><p class="muted">На последней версии нет '
            'блоков с текстом.</p></div>'
        )

    site_line = ''
    if site_url:
        site_line = (
            f'<div class="card"><p class="muted">Опубликованный сайт:</p>'
            f'<p><a href="{html.escape(site_url)}">'
            f'{html.escape(site_url)}</a></p></div>'
        )

    status = 'Открывается…'
    if not bot.has_token:
        status = 'Бот не подключён: владелец ещё не указал токен.'

    return PAGE.format(
        title=html.escape(project.name),
        header=html.escape(bot.name or f'@{bot.bot_username}'),
        content=site_line + ''.join(cards),
        status=html.escape(status),
        site_url=json.dumps(site_url),
        auth_url=json.dumps('/api/telegram/auth/'),
        bot=json.dumps(bot.bot_username),
    )


def mini_app(request, bot_username: str) -> HttpResponse:
    """Отдаёт Mini App по логину бота."""
    username = (bot_username or '').strip().lstrip('@')
    bot = TelegramBot.objects.filter(
        bot_username__iexact=username,
    ).select_related('project', 'owner').first()
    if bot is None or not bot.has_token:
        # Без токена подпись нечем проверять, а приложение без
        # проверки — это просто страница, выданная по адресу бота.
        return HttpResponse(
            PAGE.format(
                title='AuraBuilder',
                header='Mini App',
                content='<div class="card"><p>Приложение ещё не настроено. '
                        'Владелец должен указать токен бота.</p></div>',
                status='Не настроено',
                site_url='null', auth_url='"/api/telegram/auth/"',
                bot='""',
            ),
            status=404,
        )

    site_url = _published_url(bot.project)
    body = render(bot.project, bot, site_url)
    return HttpResponse(body)


def _published_url(project) -> str:
    """Адрес опубликованного сайта проекта, если он опубликован."""
    site = getattr(project, 'site', None)
    if site is None or not site.is_active:
        return ''
    return site.url()


__all__ = ['mini_app', 'render']