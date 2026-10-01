/**
 * Проверка контраста дизайн-токенов по WCAG 2.1.
 *
 * Значения читаются из docs/palette.json — единственного источника.
 * Раньше палитра дублировалась в скрипте, из-за чего расходилась с токенами.
 * Обе темы проверяются раздельно.
 *
 * Запуск: node docs/check-contrast.mjs
 * Код возврата ненулевой, если хоть одна пара не прошла порог.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const palette = JSON.parse(readFileSync(join(here, 'palette.json'), 'utf8'));

/** @typedef {{ use: string, fg: string, bg: string, min: number }} Pair */

/** @type {(t: any) => Pair[]} */
const buildPairs =
  (pairs) =>
  (t) =>
    pairs.map(([use, fg, bg, min = 4.5]) => ({ use, fg: t[fg], bg: t[bg], min }));

/** @type {[string, string, string, number?][]} */
const SPEC = [
  ['текст основной на холсте', 'textPrimary', 'canvas'],
  ['текст основной на панели', 'textPrimary', 'panel'],
  ['текст на приподнятой панели', 'textPrimary', 'panelRaised'],
  ['текст основной на appBg', 'textPrimary', 'appBg'],
  ['текст вторичный на холсте', 'textSecondary', 'canvas'],
  ['текст вторичный на панели', 'textSecondary', 'panel'],
  ['акцент-текст на холсте', 'accentText', 'canvas'],
  ['акцент-текст на панели', 'accentText', 'panel'],
  ['акцент-текст усиленный', 'accentTextStrong', 'canvas'],
  ['текст на золотой кнопке', 'onAccentSurface', 'accentSurface'],
  ['текст на золотой кнопке (hover)', 'onAccentSurfaceHover', 'accentSurfaceHover'],
  ['текст на золотой кнопке (active)', 'onAccentSurfaceActive', 'accentSurfaceActive'],
  ['текст инверсный на золоте', 'onAccentText', 'accentText'],
  ['успех на холсте', 'success', 'canvas'],
  ['предупреждение на холсте', 'warning', 'canvas'],
  ['инфо на холсте', 'info', 'canvas'],
  ['опасность на холсте', 'danger', 'canvas'],
  ['граница фокуса (UI)', 'borderFocus', 'canvas', 3],
  ['граница фокуса на панели (UI)', 'borderFocus', 'panel', 3],
  ['граница фокуса на приподнятой (UI)', 'borderFocus', 'panelRaised', 3],
];

const pairsFor = buildPairs(SPEC);

function luminance(hex) {
  const h = hex.replace('#', '');
  const channels = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const linear = channels.map((v) =>
    v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4),
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

function grade(r) {
  if (r >= 7) return 'AAA';
  if (r >= 4.5) return 'AA';
  if (r >= 3) return 'AA-large/UI';
  return 'FAIL';
}

let totalFailed = 0;
let totalPairs = 0;

for (const name of ['light', 'dark']) {
  const theme = palette[name];
  const pairs = pairsFor(theme);
  console.log(`\nТЕМА: ${name}`);
  console.log('использование'.padEnd(34) + 'пара'.padEnd(20) + 'контраст'.padEnd(11) + 'оценка');
  console.log('-'.repeat(82));
  for (const p of pairs) {
    const r = contrast(p.fg, p.bg);
    const g = grade(r);
    const ok = r >= p.min;
    if (!ok) totalFailed++;
    totalPairs++;
    console.log(
      p.use.padEnd(34) +
        `${p.fg}/${p.bg}`.padEnd(20) +
        `${r.toFixed(2)}:1`.padEnd(11) +
        `${g}${ok ? '' : '  <-- НЕ ПРОХОДИТ (нужно ' + p.min + ':1)'}`,
    );
  }
  console.log('-'.repeat(82));
}

console.log(`\nвсего пар: ${totalPairs}, не прошли: ${totalFailed}`);
process.exit(totalFailed > 0 ? 1 : 0);