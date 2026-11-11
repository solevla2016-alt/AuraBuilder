"""OG-карточка страницы: предпросмотр ссылки в мессенджерах.

Зачем это в пакете. Ссылка на сайт чаще всего появляется в чате или
ленте, и человек видит не страницу, а карточку: заголовок, адрес и
картинку. Без картинки мессенджер показывает серый прямоугольник, и
сайт выглядит недоделанным ещё до открытия.

Карточка рисуется на сервере при сборке пакета, а не запрашивается у
внешнего сервиса. Причины те же, что у остального экспорта: пакет
должен открываться без интернета и без платформы (ТЗ п.16.4), а
сторонний сервис сделал бы превью зависимым от чужого домена.

Шрифт лежит рядом с модулем (Inter, лицензия OFL, текст — в
Inter-LICENSE.txt). Системные шрифты не подходят: на Linux и Windows
они разные, и одна и та же версия документа давала бы разные картинки —
а повторный экспорт обязан совпадать (ТЗ п.16.2).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

#: Размер карточки. 1200×630 — стандарт Open Graph: так её обрезают
#: Telegram, VK и Facebook без потери заголовка.
WIDTH = 1200
HEIGHT = 630

#: Отступы внутри карточки. Вынесены в константы, чтобы подгонка
#: заголовка считала ту же ширину, что и рисование.
MARGIN = 88
TITLE_WIDTH = WIDTH - MARGIN * 2 - 190

BG = '#14161A'
TEXT = '#FFFFFF'
MUTED = '#A8AEB6'

_FONT_PATH = Path(__file__).with_name('assets') / 'InterVariable.ttf'


def _font(size: int, weight: str = 'Regular') -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_FONT_PATH), size)
    # Начертание задаётся вариацией: отдельные файлы на каждую
    # насыщенность утяжелили бы репозиторий без пользы.
    try:
        font.set_variation_by_name(weight)
    except (OSError, ValueError):
        # Старая FreeType без вариаций: остаётся Regular. Карточка
        # всё равно читается, а сборка не падает из-за шрифта.
        pass
    return font


def _fit_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Разбивает заголовок на строки и не даёт вылезти за карточку.

    Последняя строка при переполнении получает многоточие. Лучше
    оборвать длинный заголовок, чем нарисовать его поверх круга или
    за границей карточки.
    """

    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ''
    index = 0
    while index < len(words) and len(lines) < max_lines:
        word = words[index]
        trial = f'{current} {word}'.strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
            index += 1
            continue
        if current:
            lines.append(current)
            current = ''
            continue
        # Одно слово шире строки: обрезаем по символам, иначе цикл
        # не сдвинется и зависнет.
        trimmed = word
        while trimmed and draw.textlength(trimmed + '…', font=font) > max_width:
            trimmed = trimmed[:-1]
        lines.append(trimmed + '…' if trimmed else '…')
        index += 1

    if current and len(lines) < max_lines:
        lines.append(current)

    if index < len(words) and lines:
        last = lines[-1]
        while last and draw.textlength(last + '…', font=font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = (last + '…') if last else '…'
    return lines


def _display_url(base_url: str) -> str:
    """Адрес без схемы: в карточке он читается как подпись, а не как код."""

    value = (base_url or '').strip().rstrip('/')
    for prefix in ('https://', 'http://'):
        if value.startswith(prefix):
            value = value[len(prefix):]
    if not value:
        return 'AuraBuilder'
    return value[:64]


def og_card(
    project_name: str,
    page_title: str,
    base_url: str = '',
    accent: str = '',
) -> bytes:
    """PNG-карточка страницы.

    accent — фирменный цвет проекта. Он используется только как
    оформление (полоса и круг), поэтому читаемость текста от него не
    зависит: даже самый светлый акцент не делает белую надпись серой.
    """

    colour = accent or '#D9A441'
    image = Image.new('RGB', (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # Фирменная полоса слева: она узнаётся в ленте даже без чтения
    # заголовка. Круг справа — тот же цвет, но не мешает тексту.
    draw.rectangle((0, 0, 14, HEIGHT), fill=colour)
    draw.ellipse((WIDTH - 300, -150, WIDTH + 150, 300), fill=colour)
    # Внутренний круг фоном: получается кольцо, а не плоское пятно.
    draw.ellipse((WIDTH - 235, -85, WIDTH + 85, 235), fill=BG)

    label_font = _font(28, 'SemiBold')
    draw.text(
        (MARGIN, MARGIN - 10),
        (project_name or 'Сайт').upper()[:60],
        font=label_font,
        fill=colour,
    )

    title_font = _font(72, 'Bold')
    lines = _fit_lines(
        draw, page_title or project_name or 'Страница', title_font,
        TITLE_WIDTH, 3,
    )
    line_height = int(72 * 1.12)
    y = 178
    for line in lines:
        draw.text((MARGIN, y), line, font=title_font, fill=TEXT)
        y += line_height

    # Нижняя строка: короткая линия акцента, адрес и подпись платформы.
    draw.rectangle((MARGIN, HEIGHT - 128, MARGIN + 64, HEIGHT - 121), fill=colour)
    url_font = _font(30, 'Medium')
    draw.text(
        (MARGIN, HEIGHT - 96),
        _display_url(base_url),
        font=url_font,
        fill=TEXT,
    )

    note_font = _font(24, 'Regular')
    note = 'Сделано в AuraBuilder'
    note_width = draw.textlength(note, font=note_font)
    draw.text(
        (WIDTH - MARGIN - note_width, HEIGHT - 92),
        note,
        font=note_font,
        fill=MUTED,
    )

    buffer = BytesIO()
    # optimize убирает лишние байты, но не меняет пиксели: повторная
    # сборка той же версии даёт тот же файл.
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def og_colour(accent: Any) -> str:
    """Акцент только в виде #RRGGBB: значение из базы может быть любым."""

    if isinstance(accent, str) and len(accent) == 7 and accent.startswith('#'):
        try:
            int(accent[1:], 16)
        except ValueError:
            return ''
        return accent
    return ''


__all__ = ['HEIGHT', 'WIDTH', 'og_card', 'og_colour']
