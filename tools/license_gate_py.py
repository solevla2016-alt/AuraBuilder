"""
Лицензионный gate для Python-зависимостей. ТЗ п.7.1.6 и п.15.1.

Почему нужен отдельный скрипт, а не pip-флажок:

* `pip install --dry-run` и сторонние сервисы аудита передают дерево
  зависимостей за рубеж, что запрещено требованием Zero Foreign Dependency;
* метаданные пакетов неоднородны: у части нет поля License и нет
  классификаторов (Django 6.x убрал их), поэтому читаем и то, и другое,
  плюс сам текст файла лицензии.

Скрипт работает офлайн по уже установленному окружению.

Запуск: python tools/license_gate_py.py
Код возврата 1 при запрещённой лицензии.
"""

import re
import sys
from pathlib import Path

try:
    import importlib.metadata as md
except ImportError:  # Python < 3.8
    print('нужен Python 3.8 или новее')
    sys.exit(1)

# Пермиссивные и слабые копилефты (MPL/LGPL разрешены ТЗ явно).
ALLOWED = {
    'mit', 'isc', 'apache', 'apache-2.0', 'apache 2.0', 'bsd', 'bsd-2-clause',
    'bsd-3-clause', 'bsd 3-clause license', 'new bsd', '0bsd', 'cc0-1.0',
    'unlicense', 'python-2.0', 'blueoak-1.0.0', 'zlib', 'psf-2.0',
    'psf license', 'mpl-2.0', 'mozilla public license 2.0 (mpl 2.0)',
    'lgpl', 'lgpl-3.0', 'lgpl-2.1', 'unlicensed', 'dual license',
    'dual license/public domain', 'mit no attribution',
    # Мультилицензия вида «Apache-2.0 or BSD-2-Clause» (её отдаёт
    # packaging — зависимость gunicorn). Обе лицензии разрешены, выбор
    # между ними делает правообладатель, поэтому пакет допустим.
    'apache-2.0 or bsd-2-clause',
    'apache-2.0 or bsd-3-clause',
    'mit or apache-2.0',
}

# Запрещённые copyleft и source-available: ТЗ п.7.1.6.
FORBIDDEN = {
    'gpl': 'copyleft с обязательным распространением исходников',
    'gpl-2.0': 'copyleft с обязательным распространением исходников',
    'gpl-3.0': 'copyleft с обязательным распространением исходников',
    'agpl': 'сетевой copyleft — самая строгая форма',
    'agpl-3.0': 'сетевой copyleft — самая строгая форма',
    'sspl': 'серверная лицензия, не OSI',
    'r sal': 'source-available, не OSI',
    'rsal': 'source-available, не OSI',
    'busl': 'source-available с запретом на конкуренцию',
    'elastic-2.0': 'не OSI',
    'cc-by-nc': 'запрет коммерческого использования',
}

# Осознанные исключения из п.7.1.6, утверждённые заказчиком.
#
# psycopg — драйвер PostgreSQL для Django. Лицензия LGPL-3.0-only формально
# не входит в белый список «MIT, Apache 2.0, BSD», но исключение принято
# 02.10.2026 по двум основаниям:
#   1. Django не имеет драйвера на чистом Python: pg8000 лицензионно чист,
#      но бэкенд Django его не поддерживает (требует psycopg/psycopg2).
#      Альтернатива — писать собственный бэкенд, что дороже и рискованнее.
#   2. LGPL слабее GPL: при динамической линковке закрытый код раскрывать
#      не требуется, а psycopg остаётся отдельной библиотекой.
# Исключение действует только на пакет psycopg и его сборку для Windows.
ALLOWED_EXCEPTIONS = {
    'psycopg': 'LGPL-3.0-only — драйвер PostgreSQL для Django, исключение '
    'утверждено 02.10.2026 (см. docs/TZ-GAPS.md)',
    'psycopg-binary': 'LGPL-3.0-only — бинарная сборка psycopg для Windows, '
    'то же исключение, что и у psycopg',
}


def read_license_text(dist) -> str:
    """Читает файл лицензии из dist-info: у psycopg и pg8000 он там есть."""
    for name in (dist.files or []):
        parts = str(name).split('/')
        if parts[-1].upper().startswith(('LICENSE', 'COPYING')):
            try:
                return dist.read_text(name) or ''
            except Exception:
                continue
    return ''


def normalise(raw: str) -> str:
    """Приводит строку лицензии к сравнимому виду.

    Регулярка ниже убирает ТОЛЬКО хвост вроде «MIT License (MIT)» →
    «mit». Раньше она жадно съедала начало, из-за чего «BSD-3-Clause»
    превращался в «-3-clause» и лицензия переставала распознаваться.
    """
    value = re.sub(r'\s+', ' ', (raw or '').strip().lower())
    # Хвост в скобках: «mit license (mit)», «apache software license (apache 2.0)»
    value = re.sub(r'\s*\([^)]*\)\s*$', '', value)
    value = re.sub(r'\s+(license|licence)$', '', value)
    return value.strip(' .:;')


def license_of(dist) -> str:
    """Возвращает лицензию пакета из первого доступного источника."""
    meta = dist.metadata

    expr = meta.get('License-Expression')
    if expr:
        return normalise(expr)

    classifiers = [
        c.split('::')[-1] for c in (meta.get_all('Classifier') or [])
        if 'License ::' in c
    ]
    if classifiers:
        return normalise(classifiers[0])

    declared = meta.get('License')
    if declared and len(declared) < 80:
        return normalise(declared)

    # Последний рубеж: ищем характерные слова в тексте лицензии.
    text = read_license_text(dist)
    head = ' '.join(text.split())[:2000].lower()
    if 'lesser general public license' in head:
        return 'lgpl-3.0'
    if 'gnu affero' in head or 'agpl' in head:
        return 'agpl-3.0'
    if 'server side public license' in head or 'sspl' in head:
        return 'sspl'
    if 'redistribution and use in source' in head or 'mit license' in head:
        return 'mit'
    if 'redistribution and use in source and binary forms' in head:
        return 'bsd-3-clause'
    if 'apache license' in head:
        return 'apache-2.0'
    if 'mozilla public license' in head:
        return 'mpl-2.0'
    return '?'


def main() -> int:
    rows = []
    for dist in sorted(md.distributions(), key=lambda d: (d.metadata['Name'] or '').lower()):
        name = dist.metadata['Name'] or '(без имени)'
        if name.lower() == 'pip':
            continue
        rows.append((name, dist.version, license_of(dist)))

    print(f"{'пакет':26s}{'версия':14s}лицензия")
    print('-' * 70)
    bad = []
    unknown = []
    exceptions = []
    for name, version, lic in rows:
        key = name.lower().replace('_', '-')
        if key in ALLOWED_EXCEPTIONS:
            exceptions.append((name, lic, ALLOWED_EXCEPTIONS[key]))
            print(f'{name:26s}{version:14s}{lic}  <-- исключение п.7.1.6')
            continue
        mark = ''
        if lic in FORBIDDEN:
            mark = '  <-- ЗАПРЕЩЕНА'
            bad.append((name, lic))
        elif lic not in ALLOWED:
            mark = '  <-- проверить'
            unknown.append((name, lic))
        print(f'{name:26s}{version:14s}{lic}{mark}')
    print('-' * 70)
    print(
        f'пакетов: {len(rows)}, запрещённых: {len(bad)}, '
        f'неопознанных: {len(unknown)}, исключений: {len(exceptions)}'
    )

    if exceptions:
        print('\nИСКЛЮЧЕНИЯ ИЗ п.7.1.6 (утверждены заказчиком):')
        for name, lic, why in exceptions:
            print(f'  {name} — {lic}: {why}')

    if bad:
        print('\nЗАПРЕЩЁННЫЕ ЛИЦЕНЗИИ (ТЗ п.7.1.6):')
        for name, lic in bad:
            print(f'  {name} — {lic}: {FORBIDDEN[lic]}')
        return 1

    if unknown:
        print('\nНЕОПОЗНАННЫЕ (требуют ручной проверки):')
        for name, lic in unknown:
            print(f'  {name} — {lic}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
