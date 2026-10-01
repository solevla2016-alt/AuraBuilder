/** Подбор заменяющих значений: затемняем до прохождения порога. */

const BG = '#F5EFE0';

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

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function rgbToHex([r, g, b]) {
  return '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');
}

/** Линейное затемнение к чёрному с сохранением тонального соотношения. */
function darken(hex, factor) {
  return rgbToHex(hexToRgb(hex).map((v) => Math.round(v * factor)));
}

/** Подбирает максимально светлый вариант, проходящий порог. */
function solve(name, hex, min, bg = BG) {
  let best = null;
  for (let f = 1; f >= 0.3; f -= 0.01) {
    const cand = darken(hex, f);
    const r = contrast(cand, bg);
    if (r >= min) {
      best = { cand, r, f };
      break;
    }
  }
  if (best) {
    console.log(
      `${name.padEnd(26)} ${hex} (${contrast(hex, bg).toFixed(2)}:1) -> ` +
        `${best.cand} (${best.r.toFixed(2)}:1)  [x${best.f.toFixed(2)}]`,
    );
  } else {
    console.log(`${name.padEnd(26)} ${hex} -> ПОДБОР НЕ УДАЛСЯ`);
  }
}

console.log('=== текст на холсте, порог 4.5:1 ===');
solve('accentTextMuted', '#8A6A3A', 4.5);
solve('success', '#5C7A4E', 4.5);
solve('warning', '#B8873C', 4.5);
solve('info', '#5B7186', 4.5);
solve('danger', '#A4503C', 4.5);

console.log('\n=== текст на залитой кнопке, порог 4.5:1 ===');
// Кнопка светлая (#D4B896), а мы ищем ТЁМНЫЙ текст для неё.
console.log('кнопка accentSurface #D4B896, ищем тёмный текст:');
for (const cand of ['#3A3428', '#4A3F2E', '#5A4C36']) {
  console.log(`  текст ${cand} на #D4B896 -> ${contrast(cand, '#D4B896').toFixed(2)}:1`);
}
console.log('кнопка accentSurfaceActive #AE9066:');
for (const cand of ['#3A3428', '#2E281C', '#241F16']) {
  console.log(`  текст ${cand} на #AE9066 -> ${contrast(cand, '#AE9066').toFixed(2)}:1`);
}
console.log('кнопка accentSurfaceHover #C2A47E:');
for (const cand of ['#3A3428', '#4A3F2E']) {
  console.log(`  текст ${cand} на #C2A47E -> ${contrast(cand, '#C2A47E').toFixed(2)}:1`);
}

console.log('\n=== кнопка на тёмной заливке: белый текст ===');
for (const btn of ['#7A5C30', '#6B4F28']) {
  for (const fg of ['#F5EFE0', '#FFFDF5', '#FFFFFF']) {
    console.log(`  ${fg} на ${btn} -> ${contrast(fg, btn).toFixed(2)}:1`);
  }
}
