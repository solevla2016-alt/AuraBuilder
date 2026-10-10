/**
 * Генерация CSS-переменных AuraBuilder.
 *
 * Единая функция сборки: её используют и запись файла (build.mjs),
 * и Vite-плагин в apps/web (виртуальный модуль). Так токены не могут
 * разойтись между файлом на диске и тем, что отдаёт dev-сервер.
 *
 * Источник значений: docs/palette.json и packages/tokens/scales.mjs.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join } from 'node:path';
import {
  typography,
  spacing,
  shadows,
  a11y,
  effects,
  radii,
  layers,
  motion,
} from './scales.mjs';

const here = dirname(fileURLToPath(import.meta.url));

/** Корень монорепозитория: packages/tokens -> ../.. */
export const REPO_ROOT = join(here, '..', '..');

export function loadPalette() {
  return JSON.parse(readFileSync(join(REPO_ROOT, 'docs/palette.json'), 'utf8'));
}

/**
 * Порядок фиксирован: иначе diff в git станет ложным шумом.
 * Соответствует ролям в docs/design-tokens.ts.
 */
export const VARS = [
  'appBg',
  'canvas',
  'panel',
  'panelRaised',
  'panelSunken',
  'panelOverlay',
  'textPrimary',
  'textSecondary',
  'textDisabled',
  'textInverse',
  'border',
  'borderStrong',
  'borderFocus',
  'accentText',
  'accentTextStrong',
  'accentTextMuted',
  'accentSurface',
  'accentSurfaceHover',
  'accentSurfaceActive',
  'accentSurfaceSubtle',
  'accentSurfaceSunken',
  'onAccentSurface',
  'onAccentSurfaceHover',
  'onAccentSurfaceActive',
  'onAccentText',
  'success',
  'warning',
  'danger',
  'info',
  'selection',
  'selectionBorder',
  'guideLine',
  'guideMeasurement',
  'dropTarget',
];

/**
 * Слои. Компактная шкала: холст 0–4, панели 10–12, оверлеи 20–50.
 * В шаблонах z-index достигал 16 — здесь сознательно меньше,
 * чтобы порядок наложения оставался читаемым.
 */
/**
 * Добавляет префикс к именам шкалы: токены и CSS-переменные читаются
 * отдельно. Имена приводятся к kebab-case — в CSS они были такими
 * до перехода на общий источник (`--layer-canvas-content`), и ломать
 * их означало бы править редактор целиком ради того, чтобы он
 * продолжил называть то же самое.
 */
function prefixed(prefix, obj) {
  return Object.fromEntries(
    Object.entries(obj).map(([k, v]) => [
      prefix + k.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase(),
      v,
    ]),
  );
}

function block(title, obj) {
  const lines = [`  /* ${title} */`];
  for (const [k, v] of Object.entries(obj)) {
    lines.push(`  --${k}: ${v};`);
  }
  return lines.join('\n');
}

function themeVars(theme) {
  const lines = [`  /* ${theme.name} */`];
  for (const key of VARS) {
    const v = theme[key];
    if (v === undefined) {
      throw new Error(`в теме ${theme.name} нет токена "${key}"`);
    }
    lines.push(`  --${key}: ${v};`);
  }
  return lines.join('\n');
}

/**
 * @returns {{light: Record<string, string>, dark: Record<string, string>}}
 *   значения токенов по темам для Python-части платформы.
 *
 * Control Plane проверяет контраст выбранных пользователем цветов, а
 * tokens.css до него не дотягивается: сервер не запускает браузер.
 * Значения едут тем же генератором, что и CSS, иначе проверка
 * контраста считала бы по одной теме, а страница показывала другую.
 */
export function paletteValues() {
  const palette = loadPalette();
  return { light: { ...palette.light }, dark: { ...palette.dark } };
}

/** Токены, пригодные как заливка или как цвет текста. */
export function solidColorTokens(values) {
  return Object.entries(values).filter(([, v]) => /^#[0-9a-f]{6}$/i.test(v));
}

/** @returns {string} содержимое tokens.css */
export function generateTokensCss() {
  const palette = loadPalette();

  return `/*
 * CSS-переменные AuraBuilder. СГЕНЕРИРОВАНО — не править руками.
 * Источник: docs/palette.json, packages/tokens/scales.mjs
 * Генератор: packages/tokens/css.mjs
 * Правьте источник, затем: npm run tokens:build
 */

:root {
  --font-sans: ${typography.fontFamily};
  --font-mono: ${typography.fontFamilyMono};

${block(
    'типографика',
    Object.fromEntries(Object.entries(typography.scale).map(([k, v]) => [`text-${k}`, v.size])),
  )}

${block('отступы', prefixed('space-', spacing))}

${block('радиусы', prefixed('radius-', radii))}

${block('тени', prefixed('shadow-', shadows))}

${block('слои', prefixed('layer-', layers))}

${block(
    'анимация',
    prefixed('ease-', motion.easing),
  )}

${block('длительности', prefixed('duration-', motion.duration))}

  /* Мишень не меньше 44px — WCAG 2.5.5 */
  --min-target: ${a11y.minTargetSize};
  --focus-ring: var(--borderFocus);
  --focus-offset: var(--canvas);

  /* Свечение только как индикатор действия, не постоянный декор */
  --aura-drag-near: ${effects.auraDragging.near};
  --aura-drag-far: ${effects.auraDragging.far};
  --aura-active-near: ${effects.auraActive.near};
  --aura-active-far: ${effects.auraActive.far};
  --backlight-glow: ${effects.backlightGlow};

${themeVars(palette.light)}
}

[data-theme='dark'] {
${themeVars(palette.dark)}
}
`;
}
