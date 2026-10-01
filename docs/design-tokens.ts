/**
 * Design tokens редактора AuraBuilder.
 *
 * АРХИТЕКТУРА ЦВЕТА — почему так (решение от 1 октября 2026).
 *
 * Главный принцип: хром редактора нейтрален, чтобы пользователь видел
 * чужой дизайн без искажений. Тёплая заливка всего экрана (#F5EFE0 и т.п.)
 * тинтит превью чужого сайта и ломает главное обещание редактора —
 * «здесь ровно то, что увидят посетители».
 *
 * Поэтому:
 *   1. Хром (панели, холст редактора) — нейтральный серый.
 *   2. Золото — ТОЛЬКО бренд-акцент. Его мало: активные состояния,
 *      акцентные кнопки, фокус, прогресс AI. Никакого фона под текстом
 *      на всём экране.
 *   3. «Golden Sand» остаётся в brand-гайде и на публичном сайте AuraBuilder,
 *      но не в редакторе.
 *   4. Свечение и backlight сохранены, но только там, где означают
 *      «идёт действие» (drag, AI-ассистент), а не как постоянный декор.
 *
 * Токены разделены по ролям, а не по названиям цветов:
 *   accentSurface — только заливка, никогда не текст.
 *   accentText — текст и ссылки, проходят WCAG.
 * Причина: золото на светлом даёт ~1.7:1 и нечитаемо.
 *
 * Темы: light и dark. Обе проверены docs/check-contrast.mjs.
 * Значения получены расчётом относительной яркости, не подбором на глаз.
 */

import paletteJson from './palette.json';

export const neutral = paletteJson.neutral;
export const gold = paletteJson.gold;

/**
 * Светлая тема. Нейтральный хром — холодный серый с минимальным тепловым
 * сдвигом, чтобы чужой дизайн читался нейтрально. Золото присутствует
 * только как бренд-акцент и не заливает большие площади.
 */
export const lightTheme = { ...paletteJson.light, name: 'light' } as const;

/**
 * Тёмная тема. Полноценная, а не инверсия: поверхности — глубокие
 * нейтральные, акценты подобраны отдельно под контраст на них.
 *
 * Обратите внимание на onAccentText: он тёмный, а не светлый. В этой теме
 * accentText — светлое золото, употребляемое как цвет ТЕКСТА, поэтому
 * заливка под ним обязана быть тёмной. Светлый вариант давал 1.56:1.
 */
export const darkTheme = { ...paletteJson.dark, name: 'dark' } as const;

export type ThemeName = 'light' | 'dark';
export type Theme = (typeof lightTheme | typeof darkTheme) & { name: ThemeName };

export const themes: Record<ThemeName, Theme> = {
  light: lightTheme,
  dark: darkTheme,
};

export type Theme = typeof lightTheme | typeof darkTheme;
export type ThemeName = 'light' | 'dark';

export const themes: Record<ThemeName, Theme> = {
  light: lightTheme,
  dark: darkTheme,
};

/**
 * Типографика. Интервал 1.25 (major third third).
 * Inter — самохостинговый, SIL OFL. Подключение fonts.googleapis.com
 * запрещено (ТЗ п.10.1): файлы лежат в apps/web/public/fonts.
 */
export const typography = {
  fontFamily:
    "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMono: "'JetBrains Mono', 'SF Mono', Consolas, monospace",

  scale: {
    xs: { size: '0.75rem', lineHeight: 1.333, weight: 500 },
    sm: { size: '0.875rem', lineHeight: 1.429, weight: 400 },
    base: { size: '1rem', lineHeight: 1.5, weight: 400 },
    md: { size: '1.125rem', lineHeight: 1.556, weight: 400 },
    lg: { size: '1.375rem', lineHeight: 1.454, weight: 600 },
    xl: { size: '1.75rem', lineHeight: 1.429, weight: 600 },
    '2xl': { size: '2.25rem', lineHeight: 1.333, weight: 700 },
    '3xl': { size: '3rem', lineHeight: 1.25, weight: 700 },
  },
} as const;

/** Шкала отступов — шаг 4px, как базовая единица сетки. */
export const spacing = {
  unit: 4,
  xs: '4px',
  sm: '8px',
  md: '12px',
  lg: '16px',
  xl: '24px',
  '2xl': '32px',
  '3xl': '48px',
  '4xl': '64px',
  '5xl': '96px',
} as const;

export const radii = {
  sm: '4px',
  md: '8px',
  lg: '12px',
  xl: '16px',
  pill: '999px',
  round: '50%',
} as const;

/**
 * Тени. В нейтральном хроме ореол не нужен — достаточно
 * ближней тени контакта и мягкой дальней для отрыва от фона.
 * Порядок в box-shadow: от ближнего к дальнему.
 */
export const shadows = {
  none: 'none',
  sm: '0 1px 2px rgba(15, 16, 18, 0.06)',
  md: '0 2px 8px rgba(15, 16, 18, 0.08)',
  lg: '0 8px 24px rgba(15, 16, 18, 0.12)',
  xl: '0 16px 48px rgba(15, 16, 18, 0.16)',
} as const;

/**
 * Эффекты. Принцип: свечение разрешено только там, где идёт действие.
 * Нет постоянного декоративного свечения на холсте — мешает оценивать
 * контраст текста и границы блоков чужого дизайна.
 */
export const effects = {
  /**
   * Aura — применяется на перетаскиваемом элементе и активном инструменте.
   * Двухслойное: обводка + ореол.
   */
  aura: {
    dragging: {
      near: '0 0 0 1px rgba(217, 164, 65, 0.9)',
      far: '0 0 24px 4px rgba(217, 164, 65, 0.35)',
    },
    active: {
      near: '0 0 0 1px rgba(217, 164, 65, 0.6)',
      far: '0 0 16px 2px rgba(217, 164, 65, 0.22)',
    },
  },
  /**
   * Backlight — только для работающего AI-ассистента.
   * Раньше применялся постоянно ко всем панелям.
   */
  backlight: {
    glow: `radial-gradient(
      600px 300px at 50% 0%,
      rgba(217, 164, 65, 0.28) 0%,
      rgba(217, 164, 65, 0.10) 40%,
      transparent 75%
    )`,
    blur: 'blur(40px)',
  },
  /** Пульсация активности. Отключается при prefers-reduced-motion. */
  pulse: {
    duration: '2.4s',
    easing: 'cubic-bezier(0.4, 0, 0.6, 1)',
    keyframes: `
      @keyframes aura-pulse {
        0%, 100% { opacity: 0.85; }
        50% { opacity: 0.45; }
      }
    `,
  },
  /** Общие анимации дизайн-системы — вместо keyframes в каждом экране. */
  motion: {
    fadeIn: 'fade-in',
    slideUp: 'slide-up',
    scaleIn: 'scale-in',
  },
  /** Собственные easing-функции, ТЗ п.15.2 — разработаны с нуля. */
  easing: {
    standard: 'cubic-bezier(0.2, 0, 0, 1)',
    decelerate: 'cubic-bezier(0, 0, 0.2, 1)',
    accelerate: 'cubic-bezier(0.4, 0, 1, 1)',
    emphasized: 'cubic-bezier(0.2, 0, 0, 1.2)',
  },
  transition: {
    fast: '120ms',
    base: '200ms',
    slow: '320ms',
  },
} as const;

/**
 * Слои — компактная шкала (ТЗ п.4.2).
 * Холст занимает максимум экрана, поэтому панели накладываются,
 * а не сдвигают холст. Значения 0–4 + два служебных для тостов и палитры.
 */
export const layers = {
  canvas: 0,
  canvasContent: 1,
  canvasSelection: 2,
  canvasGuides: 3,
  canvasDropTarget: 4,
  floatingPalette: 10,
  bottomDock: 11,
  topBar: 12,
  drawer: 20,
  modal: 30,
  toast: 40,
  commandPalette: 50,
} as const;

/** Сетка и брейкпоинты холста (ТЗ п.6). */
export const canvas = {
  gridSize: 8,
  snapThreshold: 4,
  breakpoints: {
    mobile: 360,
    tablet: 768,
    desktop: 1024,
    wide: 1440,
  },
  devices: {
    mobile: { width: 375, label: 'Mobile' },
    tablet: { width: 768, label: 'Tablet' },
    desktop: { width: 1280, label: 'Desktop' },
  },
} as const;

/**
 * Доступность (ТЗ п.5.1.1).
 * focusRing использует borderFocus темы, а не фиксированный акцент:
 * в тёмной теме золотой текст не виден на тёмном фоне.
 */
export const a11y = {
  focusRing: '0 0 0 2px var(--focus-offset), 0 0 0 4px var(--focus-ring)',
  focusRingOffset: '2px',
  minTargetSize: '44px',
  contrast: {
    text: 4.5,
    largeText: 3,
    ui: 3,
  },
  reducedMotion: '@media (prefers-reduced-motion: reduce)',
} as const;

export const tokens = {
  neutral,
  gold,
  themes,
  typography,
  spacing,
  radii,
  shadows,
  effects,
  layers,
  canvas,
  a11y,
} as const;

export type Tokens = typeof tokens;
export default tokens;