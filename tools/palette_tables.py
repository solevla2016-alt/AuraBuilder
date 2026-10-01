"""Правка таблиц палитры в ТЗ после перехода на нейтральный хром.

Скрипт palette_replacements.py работает через `tzedit replace`, который
обходит только прямых потомков body и НЕ заходит внутрь таблиц.
Поэтому ячейки правятся адресно: (таблица, строка, столбец).

Индексы таблиц соответствуют порядку в word/document.xml:
  4 — роли палитры (11 строк)
  6 — итоговая шкала с измеренным контрастом (13 строк)
  7 — состояния акцентной кнопки (5 строк)
Таблица 5 («что не работало») НЕ трогается: это исторический замер
отклонённой палитры, он остаётся как обоснование решения.

Запуск: python tools/palette_tables.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCX = ROOT / 'AUIRA ТЗ.docx'
TZE = ROOT / 'tools' / 'tzedit.py'

ROLES_TBL, SCALE_TBL, BUTTON_TBL = 4, 6, 7

# (таблица, строка, столбец, новое значение)
EDITS = [
    # --- Таблица ролей: столбец «Роль» ---
    (ROLES_TBL, 1, 0, 'Фон холста'),
    (ROLES_TBL, 2, 0, 'Панели'),
    (ROLES_TBL, 3, 0, 'Акцент (заливка)'),
    (ROLES_TBL, 4, 0, 'Акцент (текст)'),
    (ROLES_TBL, 5, 0, 'Основной текст'),
    (ROLES_TBL, 6, 0, 'Вторичный текст'),
    (ROLES_TBL, 7, 0, 'Граница'),
    (ROLES_TBL, 8, 0, 'Тень'),
    (ROLES_TBL, 9, 0, 'Aura'),
    (ROLES_TBL, 10, 0, 'Backlight'),

    # --- Таблица ролей: столбец «Цвет» ---
    (ROLES_TBL, 1, 1, 'Нейтральный светло-серый'),
    (ROLES_TBL, 2, 1, 'Чистый белый'),
    (ROLES_TBL, 3, 1, 'Золото бренда'),
    (ROLES_TBL, 4, 1, 'Тёмное золото'),
    (ROLES_TBL, 5, 1, 'Нейтральный почти-чёрный'),
    (ROLES_TBL, 6, 1, 'Нейтральный серый'),
    (ROLES_TBL, 7, 1, 'Нейтральная полупрозрачная'),
    (ROLES_TBL, 8, 1, 'Нейтральная тень'),
    (ROLES_TBL, 9, 1, 'Свечение золота'),
    (ROLES_TBL, 10, 1, 'Свечение золота'),

    # --- Таблица ролей: столбец «HEX» ---
    (ROLES_TBL, 1, 2, '#F7F8F9'),
    (ROLES_TBL, 2, 2, '#FFFFFF'),
    (ROLES_TBL, 3, 2, '#D9A441'),
    (ROLES_TBL, 4, 2, '#7E5A12'),
    (ROLES_TBL, 5, 2, '#1A1C1E'),
    (ROLES_TBL, 6, 2, '#5B6169'),
    (ROLES_TBL, 7, 2, 'rgba(20, 22, 26, 0.10)'),
    (ROLES_TBL, 8, 2, 'rgba(15, 16, 18, 0.08)'),
    (ROLES_TBL, 9, 2, 'rgba(217, 164, 65, 0.9)'),
    (ROLES_TBL, 10, 2, 'rgba(217, 164, 65, 0.28)'),

    # --- Таблица ролей: столбец «Назначение» ---
    (ROLES_TBL, 1, 3, 'Холст редактора. Нейтральный, чтобы не тинтить пользовательский дизайн'),
    (ROLES_TBL, 2, 3, 'Панели, карточки, модалки'),
    (ROLES_TBL, 3, 3, 'CTA-кнопки и активные состояния. Только точечно, не заливает площади'),
    (ROLES_TBL, 4, 3, 'Ссылки и текст акцентных элементов на хроме (5.88:1 AA)'),
    (ROLES_TBL, 5, 3, 'Заголовки, основной текст (16.07:1 AAA)'),
    (ROLES_TBL, 6, 3, 'Подписи, вторичный текст (5.88:1 AA)'),
    (ROLES_TBL, 7, 3, 'Тонкие разделители; в тёмной теме — светлый полупрозрачный'),
    (ROLES_TBL, 8, 3, 'Мягкие тени без ореола'),
    (ROLES_TBL, 9, 3, 'Только при перетаскивании элемента, не постоянно'),
    (ROLES_TBL, 10, 3, 'Только при работе AI-ассистента, не постоянно'),

    # --- Итоговая шкала: заголовки ---
    (SCALE_TBL, 0, 1, 'HEX (светлая / тёмная)'),
    (SCALE_TBL, 0, 3, 'Контраст (AA проверен в обеих темах)'),

    # --- Итоговая шкала: значения ---
    (SCALE_TBL, 1, 1, '#F7F8F9 / #15171A'),
    (SCALE_TBL, 2, 1, '#FFFFFF / #1F2226'),
    (SCALE_TBL, 3, 1, '#D9A441 / #C9962E'),
    (SCALE_TBL, 4, 1, '#7E5A12 / #E0B85C'),
    (SCALE_TBL, 5, 1, '#6B4E0F / #EFC978'),
    (SCALE_TBL, 6, 1, '#8A6516 / #D4A94A'),
    (SCALE_TBL, 7, 1, '#1A1C1E / #E8EAED'),
    (SCALE_TBL, 8, 1, '#5B6169 / #A8AEB8'),
    (SCALE_TBL, 9, 1, '#3F6B33 / #7FA86F'),
    (SCALE_TBL, 10, 1, '#8A652D / #D9A441'),
    (SCALE_TBL, 11, 1, '#A4503C / #E08573'),
    (SCALE_TBL, 12, 1, '#3F5A70 / #7FA3C4'),

    # --- Итоговая шкала: назначение ---
    (SCALE_TBL, 1, 2, 'Холст редактора'),
    (SCALE_TBL, 3, 2, 'Заливка кнопок и активных состояний — НЕ текст'),
    (SCALE_TBL, 7, 2, 'Основной текст'),

    # --- Итоговая шкала: контраст ---
    (SCALE_TBL, 4, 3, '5.88 / 9.56 AA'),
    (SCALE_TBL, 5, 3, '7.26 / 11.37 AAA'),
    (SCALE_TBL, 6, 3, '5.00 / 8.19 AA'),
    (SCALE_TBL, 7, 3, '16.07 / 14.90 AAA'),
    (SCALE_TBL, 8, 3, '5.88 / 8.05 AA'),
    (SCALE_TBL, 9, 3, '5.87 / 6.61 AA'),
    (SCALE_TBL, 10, 3, '4.96 / 7.98 AA'),
    (SCALE_TBL, 11, 3, '5.21 / 6.65 AA'),
    (SCALE_TBL, 12, 3, '6.79 / 6.79 AA'),

    # --- Кнопка: заливка, текст, контраст ---
    (BUTTON_TBL, 1, 1, '#D9A441'),
    (BUTTON_TBL, 1, 2, '#1A1C1E'),
    (BUTTON_TBL, 1, 3, '7.60:1 AAA'),
    (BUTTON_TBL, 2, 1, '#E0AE4E'),
    (BUTTON_TBL, 2, 2, '#1A1C1E'),
    (BUTTON_TBL, 2, 3, '8.41:1 AAA'),
    (BUTTON_TBL, 3, 1, '#C9962E'),
    (BUTTON_TBL, 3, 2, '#14161A'),
    (BUTTON_TBL, 3, 3, '6.80:1 AA'),
    (BUTTON_TBL, 4, 1, '#7E5A12'),
    (BUTTON_TBL, 4, 2, '#F7F8F9'),
    (BUTTON_TBL, 4, 3, '5.88:1 AA'),
]


def main() -> int:
    if not DOCX.exists():
        print(f'not found: {DOCX}')
        return 1

    failed = 0
    for t_i, r_i, c_i, text in EDITS:
        r = subprocess.run(
            [sys.executable, str(TZE), 'cell', str(DOCX),
             str(t_i), str(r_i), str(c_i), text],
            capture_output=True, text=True, encoding='utf-8',
        )
        out = (r.stdout or '').strip()
        ok = 'set:' in out
        if not ok:
            failed += 1
            print('!!  ' + out + f'   (t{t_i} r{r_i} c{c_i} = {text[:40]})')
    print(f'\nвсего правок ячеек: {len(EDITS)}, не сработало: {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())