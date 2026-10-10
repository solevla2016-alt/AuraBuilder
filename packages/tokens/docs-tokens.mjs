/**
 * Генерация docs/design-tokens.ts — документации дизайн-системы.
 *
 * Зачем файл вообще нужен, если есть CSS-переменные: он остаётся
 * единственным местом, где шкалы описаны словами — почему золото
 * только для действий, почему акцент-текст отделён от акцентной
 * поверхности, почему свечение привязано к действию.
 *
 * Раньше значения в нём были выписаны руками и разошлись с CSS:
 * файл объявлял типы и themes дважды и в таком виде не компилировался,
 * при этом ничего не импортировал — расхождение было не видно.
 * Теперь числа подставляются генератором.
 *
 * Шкалы вставляются литералами, а не импортом: файл читают как
 * описание, и он должен оставаться верным, даже если его перенесли
 * или положили в другой проект. Темы, наоборот, импортируются из
 * palette.json — там единственный источник цветов, и дублировать его
 * в документации незачем.
 *
 * Запуск:
 *   node packages/tokens/build.mjs          вместе с остальными токенами
 *   node packages/tokens/build.mjs --check  без записи (CI)
 */

import { writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { REPO_ROOT } from './css.mjs';
import {
  typography,
  spacing,
  radii,
  shadows,
  layers,
  motion,
  effects,
  canvas,
  a11y,
} from './scales.mjs';

const OUT = join(REPO_ROOT, 'docs', 'design-tokens.ts');

/**
 * Значение в формате TypeScript. Ключи, годящиеся как идентификаторы,
 * оставляются как есть, остальные берутся в кавычки: имена вроде
 * '2xl' иначе не проходят разбор.
 */
function value(v, indent) {
  const pad = ' '.repeat(indent);
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  const inner = ' '.repeat(indent + 2);
  const lines = Object.entries(v).map(([k, item]) => {
    const key = /^[A-Za-z_][A-Za-z0-9_]*$/.test(k) ? k : JSON.stringify(k);
    return `${inner}${key}: ${value(item, indent + 2)},`;
  });
  return `{\n${lines.join('\n')}\n${pad}}`;
}

function block(name, v) {
  return `export const ${name} = ${value(v, 0)} as const;\n`;
}

export function generateDesignTokens() {
  return `/**
 * Design tokens редактора AuraBuilder.
 *
 * СГЕНЕРИРОВАНО — не править руками.
 * Числа: packages/tokens/scales.mjs и docs/palette.json.
 * Генератор: packages/tokens/build.mjs
 * Правьте источник, затем: npm run tokens:build
 *
 * АРХИТЕКТУРА ЦВЕТА — почему так (решение от 1 октября 2026).
 *
 * Главный принцип: хром редактора нейтрален, чтобы пользователь видел
 * чужой дизайн без искажений. Тёплая заливка всего экрана тинтит превью
 * чужого сайта и ломает главное обещание редактора — «здесь ровно то,
 * что увидят посетители».
 *
 * Поэтому:
 *   1. Хром (панели, холст редактора) — нейтральный серый.
 *   2. Золото — ТОЛЬКО бренд-акцент. Его мало: активные состояния,
 *      акцентные кнопки, фокус, прогресс AI. Никакого фона под текстом
 *      на всём экране.
 *   3. Свечение и backlight сохранены, но только там, где означают
 *      «идёт действие» (перетаскивание, AI-ассистент), а не как
 *      постоянный декоративный ореол: он мешал бы оценивать чужой
 *      дизайн — ровно то, ради чего существует редактор.
 *
 * Токены разделены по ролям, а не по названиям цветов:
 *   accentSurface — только заливка, никогда не текст.
 *   accentText — текст и ссылки, проходят WCAG.
 * Причина: золото на светлом даёт около 1.7:1 и нечитаемо.
 *
 * Обе темы проверяются docs/check-contrast.mjs, значения получены
 * расчётом относительной яркости, а не подбором на глаз.
 *
 * Шрифты самохостинговые: Inter и JetBrains Mono лежат в
 * apps/web/public/fonts. Подключение fonts.googleapis.com запрещено
 * (ТЗ п.10.1).
 */

import paletteJson from './palette.json';

export const neutral = paletteJson.neutral;
export const gold = paletteJson.gold;

/** Светлая тема. Нейтральный хром, золото только как бренд-акцент. */
export const lightTheme = { ...paletteJson.light, name: 'light' } as const;

/**
 * Тёмная тема. Полноценная, а не инверсия: поверхности — глубокие
 * нейтральные, акценты подобраны отдельно под контраст на них.
 *
 * Обратите внимание на onAccentText: он тёмный, а не светлый. В этой
 * теме accentText — светлое золото, употребляемое как цвет ТЕКСТА,
 * поэтому заливка под ним обязана быть тёмной.
 */
export const darkTheme = { ...paletteJson.dark, name: 'dark' } as const;

export type ThemeName = 'light' | 'dark';
export type Theme = (typeof lightTheme | typeof darkTheme) & { name: ThemeName };

export const themes: Record<ThemeName, Theme> = {
  light: lightTheme,
  dark: darkTheme,
};

/**
 * Типографика. Интервал 1.25 (major third third).
 * Inter — самохостинговый, SIL OFL.
 */
${block('typography', typography)}
/** Отступы. Кратны четырём: сетка холста опирается на шаг 8. */
${block('spacing', spacing)}
${block('radii', radii)}
${block('shadows', shadows)}
/**
 * Слои. Холст 0–4, панели 10–12, оверлеи 20–50. В шаблонах z-index
 * достигал 16 — здесь сознательно меньше, чтобы порядок наложения
 * оставался читаемым.
 */
${block('layers', layers)}
/**
 * Анимация. Длительности короткие намеренно: редактор — рабочий
 * инструмент, и анимация здесь объясняет, что произошло, а не
 * украшает. Всё, что не несёт смысла, отключается при
 * prefers-reduced-motion.
 */
${block('motion', motion)}
${block('effects', effects)}
/** Сетка и брейкпоинты холста (ТЗ п.6). */
${block('canvas', canvas)}
/** Пороги WCAG 2.1, на которые опирается проверка контраста. */
${block('a11y', a11y)}

export const tokens = {
  neutral,
  gold,
  themes,
  typography,
  spacing,
  radii,
  shadows,
  layers,
  motion,
  effects,
  canvas,
  a11y,
} as const;

export type Tokens = typeof tokens;
export default tokens;
`;
}

export function writeDesignTokens() {
  writeFileSync(OUT, generateDesignTokens(), 'utf8');
  return OUT;
}