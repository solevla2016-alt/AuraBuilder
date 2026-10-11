"""Извлечение схем свойств модулей из docs/MODULE-PROPS.md.

Продолжение цепочки каталога модулей: MODULE-PROPS.md — человекописный
документ, props.json — машинный, из него генерируются валидация на
сервере и поля панели в редакторе.

Держать схемы руками в Python и TypeScript нельзя: разошлись бы при
первом же изменении. Реестр модулей уже решён этой же схемой.

Запуск:
  python tools/props_to_registry.py
  python tools/props_to_registry.py --check
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / 'docs/MODULE-PROPS.md'
OUT_JSON = ROOT / 'packages/registry/props.json'

# Допустимые типы свойств. Всё, чего здесь нет, в панели отрисовывать
# нечем, а сервер примет — и экспорт потом не разберёт.
ALLOWED_TYPES = ('text', 'textarea', 'number', 'select', 'boolean', 'color')

MODULE_HEADING = re.compile(r'^###\s+(?P<id>[a-z]+\.[a-z][a-z_-]*)\s*$')
ROW = re.compile(
    r'^\|\s*(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*'
    r'\|\s*(?P<type>[a-z]+)\s*'
    r'\|\s*(?P<required>да|нет)\s*'
    r'\|\s*(?P<default>[^|]*)\s*'
    r'\|\s*(?P<limits>[^|]*)\s*'
    r'\|\s*(?P<desc>[^|]*)\s*\|\s*$'
)


def parse_limits(prop_type: str, raw: str) -> dict:
    """Разбирает колонку ограничений по типу свойства."""
    limits = {}
    text = raw.strip()
    if text in ('', '—'):
        return limits

    if prop_type == 'select':
        limits['options'] = [o.strip() for o in text.split(',') if o.strip()]
    elif prop_type == 'number':
        # Два формата записи, потому что в документе встречаются оба:
        #
        #   240–960, шаг 40        — диапазон и шаг словами;
        #   min: 240, max: 960, step: 40
        #
        # Раньше распознавался только первый, а документ был записан во
        # втором. Ограничения не превращались в min/max, а проверка в
        # сериализаторе молча ничего не проверяла: значение 9999 в поле
        # с «max: 960» проходило как есть.
        for part in (p.strip() for p in text.split(',')):
            low = part.lower()
            if not part:
                continue
            if low.startswith(('min:', 'min =', 'мин:')):
                value = _number(part.split(':', 1)[-1] if ':' in part else part.split('=', 1)[-1])
                if value is not None:
                    limits['min'] = value
            elif low.startswith(('max:', 'max =', 'макс:')):
                value = _number(part.split(':', 1)[-1] if ':' in part else part.split('=', 1)[-1])
                if value is not None:
                    limits['max'] = value
            elif low.startswith(('step:', 'шаг')):
                rest = part.split(':', 1)[-1] if ':' in part else part.split()[1]
                value = _number(rest)
                if value is not None:
                    limits['step'] = value
            elif '–' in part or '-' in part:
                lo, _, hi = part.replace('–', '-').partition('-')
                if lo.strip():
                    limits['min'] = _number(lo)
                if hi.strip():
                    limits['max'] = _number(hi)
    return limits


def _number(raw: str):
    """Число из строки: целое или с дробной частью.

    Дробный шаг нужен для оценки рейтинга: 4.8 — обычное значение, и
    int('4.8') бросил бы исключение прямо при генерации реестра.
    """
    text = raw.strip()
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def parse_default(prop_type: str, raw: str) -> object | None:
    text = raw.strip()
    if text in ('', '—'):
        return None
    if prop_type == 'number':
        # Дробные значения нужны оценке рейтинга: 4.8 — обычное
        # значение, и int('4.8') бросил бы исключение. Раньше
        # возвращался None, а обязательное свойство без значения
        # по умолчанию останавливало генерацию.
        return _number(text)
    if prop_type == 'boolean':
        return text.lower() in ('да', 'true', '1')
    return text


def parse() -> dict:
    if not DOC.exists():
        raise SystemExit(f'не найден документ: {DOC}')

    lines = DOC.read_text(encoding='utf-8').splitlines()
    modules: list[dict] = []
    current: dict | None = None

    for line in lines:
        heading = MODULE_HEADING.match(line)
        if heading:
            current = {'id': heading.group('id'), 'props': []}
            modules.append(current)
            continue

        if current is None:
            continue

        row = ROW.match(line)
        if not row:
            continue

        prop_type = row.group('type')
        if prop_type not in ALLOWED_TYPES:
            raise SystemExit(
                f'{current["id"]}.{row.group("name")}: неизвестный тип '
                f'"{prop_type}", допустимо {", ".join(ALLOWED_TYPES)}'
            )

        limits = parse_limits(prop_type, row.group('limits'))
        if prop_type == 'select' and not limits.get('options'):
            raise SystemExit(
                f'{current["id"]}.{row.group("name")}: select без вариантов'
            )

        default = parse_default(prop_type, row.group('default'))
        if row.group('required') == 'да' and default is None:
            raise SystemExit(
                f'{current["id"]}.{row.group("name")}: обязательное свойство '
                'без значения по умолчанию'
            )

        current['props'].append(
            {
                'name': row.group('name'),
                'type': prop_type,
                'required': row.group('required') == 'да',
                'default': default,
                'limits': limits,
                'description': row.group('desc').strip(),
            }
        )

    if not modules:
        raise SystemExit('не найдено ни одной схемы: формат документа изменился?')

    seen: set[str] = set()
    for module in modules:
        if module['id'] in seen:
            raise SystemExit(f'дубль схемы: {module["id"]}')
        seen.add(module['id'])
        if not module['props']:
            raise SystemExit(f'схема {module["id"]} пуста')

    return {
        '_comment': (
            'Схемы свойств модулей. Генерируются из docs/MODULE-PROPS.md '
            'скриптом tools/props_to_registry.py. Правьте документ, не этот файл.'
        ),
        'modules': modules,
    }


def main() -> int:
    try:
        payload = parse()
    except SystemExit as e:
        print(f'ошибка разбора: {e}')
        return 1

    content = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    check = '--check' in sys.argv

    if check:
        if not OUT_JSON.exists():
            print('props.json отсутствует — запустите python tools/props_to_registry.py')
            return 1
        if OUT_JSON.read_text(encoding='utf-8') == content:
            total = sum(len(m['props']) for m in payload['modules'])
            print(f'схемы актуальны: модулей {len(payload["modules"])}, свойств {total}')
            return 0
        print(
            'props.json разошёлся с docs/MODULE-PROPS.md — '
            'запустите python tools/props_to_registry.py'
        )
        return 1

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(content, encoding='utf-8')
    print(f'written: {OUT_JSON}')
    for module in payload['modules']:
        print(f'  {module["id"]:20s} свойств: {len(module["props"])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())