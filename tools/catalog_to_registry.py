"""Извлечение реестра модулей из docs/MODULE-CATALOG.md.

Документ написан человеком и остаётся источником правды по составу
каталога. Но в коде нужен машинно-читаемый вид: список модулей
дублировался бы в Python и TypeScript, и рано или поздно разошёлся бы.

Схема запуска:
  docs/MODULE-CATALOG.md  ->  packages/registry/modules.json
                           ->  apps/projects/module_registry.py
                           ->  apps/web/src/ui/moduleRegistry.ts

Этапы выпуска берутся из раздела «Состав MVP (28 модулей)»: там
перечислены модули этапа 3, остальные — этап 5 и 6. Так состав и этапы
берутся из одного места, а не из двух независимых списков.

Запуск:
  python tools/catalog_to_registry.py
  python tools/catalog_to_registry.py --check
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / 'docs/MODULE-CATALOG.md'
OUT_JSON = ROOT / 'packages/registry/modules.json'

# Разделы каталога. Код — буква из заголовка, id — ключ категории
# в реестре, порядок задаёт порядок групп в палитре модулей.
CATEGORIES = [
    ('A', 'structure', 'Структурные секции'),
    ('B', 'content', 'Контентные модули'),
    ('C', 'data', 'Модули данных'),
    ('D', 'commerce', 'Коммерческие модули'),
    ('E', 'trust', 'Секции доверия и соответствия'),
]

# Этапы выпуска (ТЗ п.12, состав по этапам).
STAGE_MVP = 3
STAGE_EXPANSION_1 = 5
STAGE_EXPANSION_2 = 6

# Вид блока на холсте: от него зависит заливка в редакторе.
# Не путать с категорией: data.list лежит в категории data, но
# рисуется как текстовый блок, а не как секция.
KIND_BY_CATEGORY = {
    'structure': 'section',
    'content': 'text',
    'media': 'text',
    'data': 'text',
    'commerce': 'text',
    'trust': 'text',
}

# Строка таблицы: | `id` | Название | Назначение | Примечание |
# В id допускается дефис: legal.age-mark, legal.ad-mark (ТЗ п.9.5).
ROW = re.compile(r'^\|\s*`(?P<id>[a-z]+\.[a-z][a-z_-]*)`\s*\|(?P<name>[^|]*)\|')
# Раздел категории: ### A. Структурные секции
SECTION = re.compile(r'^###\s*(?P<code>[A-E])\.')
# Ячейка состава MVP: | A. Структурные (8) | header, hero, ... |
MVP_ROW = re.compile(r'^\|\s*(?P<code>[A-E])\.\s*[^|]*\|\s*(?P<list>[^|]*)\|\s*$')
# Отложенные модули: «Отложено до этапа 5: gallery, steps, ...».
# Часть правил задана словами: «вся категория D» — это 12 модулей,
# а не один, поэтому такие формулировки разворачиваются по категориям.
DEFERRED = re.compile(r'Отложено до этапа\s*(?P<stage>\d+)\s*:\s*(?P<list>[^.]+)', re.S)
WHOLE_CATEGORY = re.compile(r'вся категория\s*([A-E])')

# Префиксы id, по которым определяется категория, если она не задана
# заголовком (например, media.* внутри раздела контентных модулей).
PREFIX_CATEGORY = {
    'section': 'A',
    'text': 'B',
    'media': 'B',
    'link': 'B',
    'form': 'B',
    'code': 'B',
    'nav': 'B',
    'data': 'C',
    'schema': 'C',
    'shop': 'D',
    'order': 'D',
    'trust': 'E',
    'legal': 'E',
}


#: Названия, которые в каталоге записаны по-человечески, а в реестре
#: имеют другой id. Без этого «custom code» не совпал бы с code.custom
#: и модуль молча уезжал из MVP на этап 5: в документе 27 модулей, а
#: в реестре получалось 26, и расхождения никто не замечал — генератор
#: проверял сам себя.
NAME_ALIASES = {
    'custom_code': 'code.custom',
}


def split_modules(text: str) -> list[str]:
    """Разбирает список «header, hero, custom code» в названия модулей.

    В списках MVP названия записаны по-человечески («custom code» вместо
    code.custom), поэтому пробелы сводим к подчёркиванию, а известные
    синонимы переводим в id из реестра.
    """
    out = []
    for raw in text.split(','):
        item = raw.strip().strip('`').strip()
        if not item or item in {'и вся категория E', 'и вся категория D'}:
            continue
        item = item.replace(' ', '_').replace('-', '_')
        out.append(NAME_ALIASES.get(item, item))
    return out


def category_code_for(module_id: str, fallback: str | None) -> str:
    """Категория по префиксу id, с откатом на раздел каталога."""
    if fallback:
        return fallback
    prefix = module_id.split('.')[0]
    return PREFIX_CATEGORY.get(prefix, 'B')


def parse_catalog() -> list[dict]:
    text = CATALOG.read_text(encoding='utf-8')
    lines = text.splitlines()

    # Сначала собираем состав MVP: категория -> список названий.
    mvp: dict[str, set[str]] = {}
    deferred: dict[int, set[str]] = {}
    in_mvp = False

    for line in lines:
        if line.startswith('## '):
            in_mvp = 'Состав MVP' in line
            continue

        if in_mvp:
            row = MVP_ROW.match(line)
            if row:
                mvp.setdefault(row.group('code'), set()).update(
                    split_modules(row.group('list'))
                )

        deferred_match = DEFERRED.search(line)
        if deferred_match:
            stage = int(deferred_match.group('stage'))
            body = deferred_match.group('list')
            names = set(split_modules(body))
            # «вся категория D» разворачиваем в флаг по категории:
            # конкретные имена станут известны при обходе разделов.
            for whole in WHOLE_CATEGORY.findall(body):
                names.add(f'@{whole}')
            deferred.setdefault(stage, set()).update(names)

    # Теперь обходим разделы категорий и собираем модули с названиями.
    modules: list[dict] = []
    seen: set[str] = set()
    current_code: str | None = None

    for line in lines:
        section = SECTION.match(line)
        if section:
            current_code = section.group('code')
            continue

        if line.startswith('## ') or line.startswith('# '):
            current_code = None

        row = ROW.match(line)
        if not row:
            continue

        module_id = row.group('id')
        name = row.group('name').strip()
        if module_id in seen:
            raise SystemExit(f'дубль модуля в каталоге: {module_id}')
        seen.add(module_id)

        code = category_code_for(module_id, current_code)
        category = next((cid for c, cid, _ in CATEGORIES if c == code), None)
        if category is None:
            raise SystemExit(f'модуль {module_id}: неизвестная категория {code}')

        label = next((lab for c, _, lab in CATEGORIES if c == code), category)

        # Этап выпуска. Списки MVP даны по коротким именам внутри строки
        # категории, поэтому сверять нужно по паре (категория, имя), а не
        # по имени одному: «form» есть и в action.form (MVP, категория B),
        # и в data.form (отложен до этапа 5, категория C).
        # Короткое имя приводим к тому же виду, что и записи в списках:
        # legal.ad-mark -> ad_mark, иначе сверка с MVP молча не сойдётся.
        short_name = module_id.split('.')[-1].replace('-', '_')
        mvp_names = mvp.get(code, set())

        def in_stage(stage: int) -> bool:
            names = deferred.get(stage, set())
            if module_id in names or name in names or short_name in names:
                return True
            # «вся категория X» — принадлежность к категории решает всё
            return f'@{code}' in names

        # Сверять нужно и по полному id, и по короткому имени: в списках
        # MVP названия записаны по-человечески («custom code»), и после
        # подстановки синонима там лежит code.custom, а не «custom».
        # Раньше проверялось только короткое имя, code.custom уезжал на
        # этап 5, и в реестре получалось 26 модулей MVP вместо 27 —
        # расхождение с документом не ловилось, потому что генератор
        # проверял сам себя.
        if module_id in mvp_names or short_name in mvp_names:
            stages = [STAGE_MVP]
        elif in_stage(STAGE_EXPANSION_2):
            stages = [STAGE_EXPANSION_2]
        else:
            stages = [STAGE_EXPANSION_1]

        # Модуль из списка MVP обязан быть на этапе 3. Раньше такая
        # ошибка проходила молча: генератор сам себя и проверял.
        if stages != [STAGE_MVP] and (
            module_id in mvp_names or short_name in mvp_names
        ):
            raise SystemExit(
                f'модуль {module_id} есть в списке MVP, но попал на этап '
                f'{stages[0]}: проверьте синоним в NAME_ALIASES'
            )

        modules.append(
            {
                'id': module_id,
                'name': name,
                'category': category,
                'categoryLabel': label,
                'kind': KIND_BY_CATEGORY.get(category, 'text'),
                'stages': stages,
                'minStage': min(stages),
            }
        )

    # Сортировка по этапу, затем по категории и имени — палитра модулей
    # показывает группы в порядке категорий, а внутри этапа порядок должен
    # быть стабильным между запусками генератора.
    category_order = {cid: i for i, (_, cid, _) in enumerate(CATEGORIES)}
    modules.sort(
        key=lambda m: (
            m['minStage'],
            category_order.get(m['category'], 99),
            m['name'].lower(),
        )
    )

    return modules


def render_json(modules: list[dict]) -> str:
    payload = {
        '_comment': (
            'Реестр модулей редактора. Генерируется из docs/MODULE-CATALOG.md '
            'скриптом tools/catalog_to_registry.py. Правьте каталог, не этот файл.'
        ),
        'total': len(modules),
        'categories': [
            {'code': code, 'id': cid, 'label': label} for code, cid, label in CATEGORIES
        ],
        'modules': modules,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'


def main() -> int:
    if not CATALOG.exists():
        print(f'не найден каталог: {CATALOG}')
        return 1

    modules = parse_catalog()
    if not modules:
        print('не найдено ни одного модуля — формат каталога изменился?')
        return 1

    content = render_json(modules)
    check = '--check' in sys.argv

    if check:
        if not OUT_JSON.exists():
            print('modules.json отсутствует — запустите python tools/catalog_to_registry.py')
            return 1
        if OUT_JSON.read_text(encoding='utf-8') == content:
            print(f'реестр актуален: модулей {len(modules)}')
            return 0
        print(
            'modules.json разошёлся с docs/MODULE-CATALOG.md — '
            'запустите python tools/catalog_to_registry.py'
        )
        return 1

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(content, encoding='utf-8')

    by_category: dict[str, int] = {}
    by_stage: dict[int, int] = {}
    for module in modules:
        by_category[module['category']] = by_category.get(module['category'], 0) + 1
        by_stage[module['minStage']] = by_stage.get(module['minStage'], 0) + 1

    print(f'written: {OUT_JSON}')
    print(f'всего модулей: {len(modules)}')
    for code, cid, label in CATEGORIES:
        print(f'  {code} {label:32s} {by_category.get(cid, 0):3d}')
    print('по этапам:', ', '.join(f'этап {s}: {n}' for s, n in sorted(by_stage.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())