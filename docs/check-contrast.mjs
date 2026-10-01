/** Проверка контраста токенов дизайн-системы по WCAG 2.1. */

/** @typedef {{ fg: string, bg: string, use: string, min: number }} Pair */

/** @type {Pair[]} */
const PAIRS = [
  { fg: '#3A3428', bg: '#F5EFE0', use: 'текст основной на холсте', min: 4.5 },
  { fg: '#3A3428', bg: '#FBF6E8', use: 'текст на панели', min: 4.5 },
  { fg: '#3A3428', bg: '#FFFDF5', use: 'текст на приподнятой панели', min: 4.5 },
  { fg: '#6B6250', bg: '#F5EFE0', use: 'текст вторичный на холсте', min: 4.5 },
  { fg: '#6B6250', bg: '#FBF6E8', use: 'текст вторичный на панели', min: 4.5 },
  { fg: '#7A5C30', bg: '#F5EFE0', use: 'акцент-текст на холсте', min: 4.5 },
  { fg: '#7A5C30', bg: '#FBF6E8', use: 'акцент-текст на панели', min: 4.5 },
  { fg: '#6B4F28', bg: '#F5EFE0', use: 'акцент-текст усиленный', min: 4.5 },
  { fg: '#F5EFE0', bg: '#7A5C30', use: 'текст на акцентной кнопке', min: 4.5 },
  { fg: '#3A3428', bg: '#D4B896', use: 'текст на кнопке (обычная)', min: 4.5 },
  { fg: '#3A3428', bg: '#C2A47E', use: 'текст на кнопке (hover)', min: 4.5 },
  { fg: '#241F16', bg: '#AE9066', use: 'текст на кнопке (active)', min: 4.5 },
  { fg: '#F5EFE0', bg: '#7A5C30', use: 'текст на кнопке (инверсная)', min: 4.5 },
  { fg: '#866738', bg: '#F5EFE0', use: 'акцент приглушённый', min: 4.5 },
  { fg: '#58754B', bg: '#F5EFE0', use: 'успех на холсте', min: 4.5 },
  { fg: '#8A652D', bg: '#F5EFE0', use: 'предупреждение на холсте', min: 4.5 },
  { fg: '#596F83', bg: '#F5EFE0', use: 'инфо на холсте', min: 4.5 },
  { fg: '#A4503C', bg: '#F5EFE0', use: 'опасность на холсте', min: 4.5 },
  { fg: '#7A5C30', bg: '#F5EFE0', use: 'граница фокуса', min: 3 },
];

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

let failed = 0;
console.log('использование'.padEnd(34) + 'пара'.padEnd(20) + 'контраст'.padEnd(11) + 'оценка');
console.log('-'.repeat(82));
for (const p of PAIRS) {
  const r = contrast(p.fg, p.bg);
  const g = grade(r);
  const ok = r >= p.min;
  if (!ok) failed++;
  console.log(
    p.use.padEnd(34) +
      `${p.fg}/${p.bg}`.padEnd(20) +
      `${r.toFixed(2)}:1`.padEnd(11) +
      `${g}${ok ? '' : '  <-- НЕ ПРОХОДИТ (нужно ' + p.min + ':1)'}`,
  );
}
console.log('-'.repeat(82));
console.log(`всего пар: ${PAIRS.length}, не прошли: ${failed}`);
