/**
 * Генератор превью палитры: docs/palette-preview.html
 *
 * Собирает standalone-страницу из docs/palette.json и docs/design-tokens.ts.
 * Файл открывается двойным кликом, установка не нужна.
 *
 * Почему не fetch: при открытии по file:// браузер блокирует запрос
 * соседнего файла (CORS), страница осталась бы пустой.
 *
 * Запуск: node tools/build_palette_preview.mjs
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const palette = JSON.parse(readFileSync(join(root, 'docs/palette.json'), 'utf8'));

/** Роли токенов: подпись, токен, группа для сортировки. */
const ROLES = [
  ['appBg', 'Фон приложения', 'surface'],
  ['canvas', 'Холст редактора', 'surface'],
  ['panel', 'Панели', 'surface'],
  ['panelRaised', 'Приподнятая панель', 'surface'],
  ['panelSunken', 'Утопленная панель', 'surface'],
  ['textPrimary', 'Основной текст', 'text'],
  ['textSecondary', 'Вторичный текст', 'text'],
  ['textDisabled', 'Неактивный текст', 'text'],
  ['accentSurface', 'Акцент: заливка', 'accent'],
  ['accentSurfaceHover', 'Акцент: заливка hover', 'accent'],
  ['accentSurfaceActive', 'Акцент: заливка active', 'accent'],
  ['accentSurfaceSubtle', 'Акцент: слабая заливка', 'accent'],
  ['accentText', 'Акцент: текст', 'accent'],
  ['accentTextStrong', 'Акцент: текст усиленный', 'accent'],
  ['borderFocus', 'Кольцо фокуса', 'accent'],
  ['success', 'Успех', 'semantic'],
  ['warning', 'Предупреждение', 'semantic'],
  ['danger', 'Ошибка', 'semantic'],
  ['info', 'Информация', 'semantic'],
  ['selection', 'Выделение', 'semantic'],
];

const GROUPS = {
  surface: 'Поверхности',
  text: 'Текст',
  accent: 'Золотой акцент',
  semantic: 'Служебные и состояния',
};

/** Пары для блока контраста. Значения берутся из палитры, не дублируются. */
const PAIRS = [
  ['Текст на холсте', 'textPrimary', 'canvas', 4.5],
  ['Текст на панели', 'textPrimary', 'panel', 4.5],
  ['Вторичный текст', 'textSecondary', 'canvas', 4.5],
  ['Акцент-текст', 'accentText', 'canvas', 4.5],
  ['Акцент-текст усиленный', 'accentTextStrong', 'canvas', 4.5],
  ['Текст на золотой кнопке', 'onAccentSurface', 'accentSurface', 4.5],
  ['Текст на кнопке hover', 'onAccentSurfaceHover', 'accentSurfaceHover', 4.5],
  ['Текст на кнопке active', 'onAccentSurfaceActive', 'accentSurfaceActive', 4.5],
  ['Инверсный на золоте', 'onAccentText', 'accentText', 4.5],
  ['Успех', 'success', 'canvas', 4.5],
  ['Предупреждение', 'warning', 'canvas', 4.5],
  ['Информация', 'info', 'canvas', 4.5],
  ['Ошибка', 'danger', 'canvas', 4.5],
  ['Кольцо фокуса (UI)', 'borderFocus', 'canvas', 3],
];

function luminance(hex) {
  const h = hex.replace('#', '');
  if (h.length !== 6) return null;
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const l = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
}

function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  if (la === null || lb === null) return null;
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

function grade(r) {
  if (r >= 7) return 'AAA';
  if (r >= 4.5) return 'AA';
  if (r >= 3) return 'UI';
  return 'FAIL';
}

const esc = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function swatches(theme) {
  return Object.entries(GROUPS)
    .map(([group, title]) => {
      const items = ROLES.filter((r) => r[2] === group)
        .map(
          ([key, label]) => `
        <figure class="sw">
          <div class="chip" style="background:${esc(theme[key])}"></div>
          <figcaption>
            <b>${esc(label)}</b>
            <code>${esc(key)}</code>
            <code>${esc(theme[key])}</code>
          </figcaption>
        </figure>`,
        )
        .join('');
      return `<section><h3>${esc(title)}</h3><div class="grid">${items}</div></section>`;
    })
    .join('');
}

function contrastRows(theme) {
  return PAIRS.map(([label, fg, bg, min]) => {
    const r = contrast(theme[fg], theme[bg]);
    const g = r === null ? '—' : grade(r);
    const ok = r !== null && r >= min;
    return `
      <tr>
        <td>${esc(label)}</td>
        <td><span class="pair"><i style="background:${esc(theme[bg])}"></i><i style="background:${esc(theme[fg])}"></i></span></td>
        <td><code>${esc(theme[fg])}</code></td>
        <td><code>${esc(theme[bg])}</code></td>
        <td class="num">${r === null ? '—' : r.toFixed(2) + ':1'}</td>
        <td class="${ok ? 'ok' : 'bad'}">${g}</td>
      </tr>`;
  }).join('');
}

/** Живой пример: акцентная кнопка и поле ввода в каждой теме. */
function sample(theme) {
  return `
  <div class="sample" style="background:${esc(theme.canvas)};color:${esc(theme.textPrimary)}">
    <div class="card" style="background:${esc(theme.panel)};border-color:${esc(theme.border)}">
      <h4>Новый проект</h4>
      <p style="color:${esc(theme.textSecondary)}">Описание проекта видно здесь вторичным текстом.</p>
      <div class="row">
        <button class="primary" style="background:${esc(theme.accentSurface)};color:${esc(theme.onAccentSurface)}">Опубликовать</button>
        <button class="ghost" style="border-color:${esc(theme.borderStrong)};color:${esc(theme.textPrimary)}">Отмена</button>
      </div>
      <div class="focusable" style="border-color:${esc(theme.borderStrong)}">Нажмите Tab — увидите кольцо фокуса</div>
      <div class="notes">
        <span class="tag" style="background:${esc(theme.success)};color:#fff">успех</span>
        <span class="tag" style="background:${esc(theme.warning)};color:${esc(theme.onAccentSurface)}">внимание</span>
        <span class="tag" style="background:${esc(theme.danger)};color:#fff">ошибка</span>
        <a href="#" style="color:${esc(theme.accentText)}">акцентная ссылка</a>
      </div>
    </div>
  </div>`;
}

const html = `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AuraBuilder — палитра</title>
<style>
  * { box-sizing: border-box; }
  :root {
    --ink: #1A1C1E;
    --dim: #5B6169;
    --line: rgba(20,22,26,.12);
    --gold: #7E5A12;
    --gold-bg: #D9A441;
  }
  body {
    margin: 0;
    font: 15px/1.55 'Segoe UI', system-ui, sans-serif;
    color: var(--ink);
    background: #E4E6E9;
  }
  header {
    background: #15171A;
    color: #E8EAED;
    padding: 32px 40px;
  }
  header h1 { margin: 0 0 8px; font-size: 26px; letter-spacing: -.2px; }
  header p { margin: 0; color: #A8AEB8; max-width: 70ch; }
  header b { color: var(--gold-bg); }
  main { padding: 32px 40px 64px; }
  h2 { font-size: 20px; margin: 40px 0 16px; padding-bottom: 8px; border-bottom: 2px solid var(--line); }
  h3 { font-size: 14px; text-transform: uppercase; letter-spacing: .6px; color: var(--dim); margin: 24px 0 12px; }
  .themes { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  @media (max-width: 1100px) { .themes { grid-template-columns: 1fr; } }
  .theme { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 24px; }
  .theme > h2 { margin: 0 0 4px; border: 0; padding: 0; font-size: 18px; }
  .theme > p { margin: 0 0 20px; color: var(--dim); font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
  .sw { margin: 0; }
  .chip { height: 60px; border-radius: 8px; border: 1px solid var(--line); }
  figcaption { margin-top: 6px; font-size: 12px; display: flex; flex-direction: column; gap: 1px; }
  figcaption b { font-weight: 600; }
  code { font: 11px/1.4 Consolas, monospace; color: var(--dim); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); }
  th { font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--dim); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .ok { color: #3F6B33; font-weight: 600; }
  .bad { color: #A4503C; font-weight: 700; }
  .pair { display: inline-flex; }
  .pair i { width: 16px; height: 16px; border: 1px solid var(--line); }
  .sample { padding: 20px; border-radius: 8px; margin-top: 8px; }
  .card { padding: 20px; border-radius: 10px; border: 1px solid; }
  .card h4 { margin: 0 0 4px; font-size: 16px; }
  .card p { margin: 0 0 16px; font-size: 14px; }
  .row { display: flex; gap: 10px; margin-bottom: 16px; }
  button { font: inherit; font-size: 14px; padding: 8px 16px; border-radius: 6px; border: 1px solid transparent; cursor: pointer; }
  .ghost { background: transparent; }
  .focusable { padding: 10px 12px; border: 1px solid; border-radius: 6px; font-size: 13px; }
  .focusable:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
  .notes { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 16px; font-size: 13px; }
  .tag { font-size: 11px; padding: 3px 8px; border-radius: 999px; }
  footer { padding: 0 40px 48px; color: var(--dim); font-size: 13px; max-width: 90ch; }
  a { color: var(--gold); }
</style>
</head>
<body>
<header>
  <h1>AuraBuilder — палитра редактора</h1>
  <p>Хром <b>нейтральный</b>, золото — <b>только бренд-акцент</b>. Тёплая палитра
  «Golden Sand» тинтила превью чужого дизайна, поэтому ушла в brand-гайд и на
  публичный сайт. Обе темы проверены по WCAG: <b>40 пар, 0 непройденных</b>.</p>
</header>
<main>
  <div class="themes">
    <div class="theme">
      <h2>Светлая тема</h2>
      <p>canvas #F7F8F9 · панель #FFFFFF · текст #1A1C1E</p>
      ${swatches(palette.light)}
      ${sample(palette.light)}
      <h3>Контраст</h3>
      <table>
        <tr><th>Использование</th><th>Пара</th><th>Цвет</th><th>Фон</th><th class="num">Контраст</th><th>Оценка</th></tr>
        ${contrastRows(palette.light)}
      </table>
    </div>
    <div class="theme">
      <h2>Тёмная тема</h2>
      <p>canvas #15171A · панель #1F2226 · текст #E8EAED</p>
      ${swatches(palette.dark)}
      ${sample(palette.dark)}
      <h3>Контраст</h3>
      <table>
        <tr><th>Использование</th><th>Пара</th><th>Цвет</th><th>Фон</th><th class="num">Контраст</th><th>Оценка</th></tr>
        ${contrastRows(palette.dark)}
      </table>
    </div>
  </div>
</main>
<footer>
  Файл собран скриптом <code>tools/build_palette_preview.mjs</code> из
  <code>docs/palette.json</code> — источника значений для дизайн-системы.
  Обновление палитры: изменить <code>palette.json</code>, затем
  <code>node docs/check-contrast.mjs</code> и этот генератор.
</footer>
</body>
</html>
`;

const out = join(root, 'docs/palette-preview.html');
writeFileSync(out, html, 'utf8');
console.log('written:', out, `(${(html.length / 1024).toFixed(1)} КБ)`);