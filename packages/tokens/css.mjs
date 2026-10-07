/**
 * Генерация CSS-переменных AuraBuilder.
 *
 * Единая функция сборки: её используют и запись файла (build.mjs),
 * и Vite-плагин в apps/web (виртуальный модуль). Так токены не могут
 * разойтись между файлом на диске и тем, что отдаёт dev-сервер.
 *
 * Источник значений: docs/palette.json.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join } from 'node:path';

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
const LAYERS = {
  'layer-canvas': 0,
  'layer-canvas-content': 1,
  'layer-canvas-selection': 2,
  'layer-canvas-guides': 3,
  'layer-canvas-drop': 4,
  'layer-floating-palette': 10,
  'layer-bottom-dock': 11,
  'layer-top-bar': 12,
  'layer-drawer': 20,
  'layer-modal': 30,
  'layer-toast': 40,
  'layer-command-palette': 50,
};

const SPACING = {
  'space-xs': '4px',
  'space-sm': '8px',
  'space-md': '12px',
  'space-lg': '16px',
  'space-xl': '24px',
  'space-2xl': '32px',
  'space-3xl': '48px',
  'space-4xl': '64px',
  'space-5xl': '96px',
};

const RADII = {
  'radius-sm': '4px',
  'radius-md': '8px',
  'radius-lg': '12px',
  'radius-xl': '16px',
  'radius-pill': '999px',
};

const SHADOWS = {
  'shadow-sm': '0 1px 2px rgba(15, 16, 18, 0.06)',
  'shadow-md': '0 2px 8px rgba(15, 16, 18, 0.08)',
  'shadow-lg': '0 8px 24px rgba(15, 16, 18, 0.12)',
  'shadow-xl': '0 16px 48px rgba(15, 16, 18, 0.16)',
};

const MOTION = {
  'ease-standard': 'cubic-bezier(0.2, 0, 0, 1)',
  'ease-decelerate': 'cubic-bezier(0, 0, 0.2, 1)',
  'ease-accelerate': 'cubic-bezier(0.4, 0, 1, 1)',
  'ease-emphasized': 'cubic-bezier(0.2, 0, 0, 1.2)',
  'duration-fast': '120ms',
  'duration-base': '200ms',
  'duration-slow': '320ms',
};

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
 * Источник: docs/palette.json
 * Генератор: packages/tokens/css.mjs
 * Правьте источник, затем: npm run tokens:build
 */

:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', Consolas, monospace;

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-md: 1.125rem;
  --text-lg: 1.375rem;
  --text-xl: 1.75rem;
  --text-2xl: 2.25rem;
  --text-3xl: 3rem;

${block('отступы', SPACING)}

${block('радиусы', RADII)}

${block('тени', SHADOWS)}

${block('слои', LAYERS)}

${block('анимация', MOTION)}

  /* Мишень не меньше 44px — WCAG 2.5.5 */
  --min-target: 44px;
  --focus-ring: var(--borderFocus);
  --focus-offset: var(--canvas);

  /* Свечение только как индикатор действия, не постоянный декор */
  --aura-drag-near: 0 0 0 1px rgba(217, 164, 65, 0.9);
  --aura-drag-far: 0 0 24px 4px rgba(217, 164, 65, 0.35);
  --aura-active-near: 0 0 0 1px rgba(217, 164, 65, 0.6);
  --aura-active-far: 0 0 16px 2px rgba(217, 164, 65, 0.22);
  --backlight-glow: radial-gradient(
    600px 300px at 50% 0%,
    rgba(217, 164, 65, 0.28) 0%,
    rgba(217, 164, 65, 0.1) 40%,
    transparent 75%
  );

${themeVars(palette.light)}
}

[data-theme='dark'] {
${themeVars(palette.dark)}
}
`;
}
