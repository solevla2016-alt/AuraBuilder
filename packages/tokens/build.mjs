/**
 * Запись сгенерированных токенов в packages/tokens/dist/tokens.css.
 *
 * Файл нужен для:
 *   - предпросмотра палитры и статических страниц;
 *   - режима --check в CI.
 *
 * Vite при этом токены не читает: он получает их виртуальным модулем
 * (см. apps/web/vite.config.ts) — так dev-сервер не зависит от того,
 * успел ли отработать этот скрипт.
 *
 * Запуск:
 *   node packages/tokens/build.mjs
 *   node packages/tokens/build.mjs --check
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join } from 'node:path';
import { generateTokensCss, paletteValues, solidColorTokens, VARS } from './css.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, 'dist');
const outFile = join(outDir, 'tokens.css');

// Control Plane проверяет контраст цветов, которые выбрал пользователь,
// и нуждается в значениях токенов на сервере. Модуль генерируется
// здесь же: рукописный список токенов разошёлся бы с палитрой при
// первом же добавлении цвета, и проверка молча принимала бы его.
const pythonFile = join(here, '..', '..', 'apps', 'projects', 'palette_tokens.py');

/**
 * Python-модуль со значениями токенов.
 *
 * В него попадают только непрозрачные цвета: rgba со слоем меньше
 * единицы описывает полупрозрачную подложку, а не поверхность, и
 * выбирать её фоном компонента нельзя — под ней окажется родительская
 * поверхность, и рассчитанный контраст перестанет быть настоящим.
 */
function generatePython() {
  const themes = paletteValues();
  const names = VARS.filter((key) =>
    Object.values(themes).every((t) => solidColorTokens(t).some(([n]) => n === key)),
  );
  const literal = (value) => JSON.stringify(value);
  const dict = (theme) =>
    `{${names.map((key) => `${literal(key)}: ${literal(themes[theme][key])}`).join(', ')}}`;

  return `"""Значения токенов палитры для Control Plane.

* СГЕНЕРИРОВАНО — не править руками. Источник: docs/palette.json
 * Генератор: packages/tokens/build.mjs
 * Правьте источник, затем: npm run tokens:build

Нужен серверу для одной вещи: проверить контраст между фоном и текстом,
которые пользователь выбрал в библиотеке компонентов (ТЗ п.3.1).
Считать его на глаз нельзя, а взять палитру из браузера сервер не может.

Список ограничен непрозрачными цветами: полупрозрачные токены
описывают наложения, а не поверхности, и контраст с ними зависит от
того, что окажется под ними.
"""

from __future__ import annotations

#: Имена токенов, пригодных как заливка или как цвет текста.
SOLID_TOKENS: tuple[str, ...] = (
${names.map((n) => `    ${literal(n)},`).join('\n')}
)

#: Значения по темам. Тема выбирается на клиенте, поэтому контраст
#: проверяется по обеим сразу.
THEMES: dict[str, dict[str, str]] = {
    'light': ${dict('light')},
    'dark': ${dict('dark')},
}
`;
}

const check = process.argv.includes('--check');
const css = generateTokensCss();
const python = generatePython();

if (check) {
  const current = existsSync(outFile) ? readFileSync(outFile, 'utf8') : null;
  const currentPy = existsSync(pythonFile) ? readFileSync(pythonFile, 'utf8') : null;
  const cssOk = current === css;
  const pyOk = currentPy === python;
  if (cssOk && pyOk) {
    console.log('tokens.css актуален, palette_tokens.py актуален');
    process.exit(0);
  }
  console.error(
    [
      current === null
        ? 'tokens.css отсутствует — запустите npm run tokens:build'
        : !cssOk
          ? 'tokens.css разошёлся с docs/palette.json — запустите npm run tokens:build'
          : null,
      currentPy === null
        ? 'apps/projects/palette_tokens.py отсутствует — запустите npm run tokens:build'
        : !pyOk
          ? 'palette_tokens.py разошёлся с docs/palette.json — запустите npm run tokens:build'
          : null,
    ]
      .filter(Boolean)
      .join('\n'),
  );
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, css, 'utf8');
writeFileSync(pythonFile, python, 'utf8');
console.log(
  `written: ${outFile} (${VARS.length} переменных на тему, ${(css.length / 1024).toFixed(1)} КБ)`,
);
console.log(`written: ${pythonFile} (значения токенов для Control Plane)`);
