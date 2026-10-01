/**
 * Design tokens редактора AuraBuilder.
 *
 * Палитра «Golden Sand» с эффектами Aura и Backlight (ТЗ п.5.1, п.5.1.1).
 *
 * ВАЖНО: токены разделены по ролям, а не по названиям цветов.
 * accent-surface — только заливка и свечение, никогда не текст.
 * accent-text — текст и ссылки на светлом фоне.
 * Это следствие замера контраста: #D4B896 на #F5EFE0 даёт 1.65:1 и
 * не проходит WCAG (требуется 4.5:1 для текста).
 *
 * Источник значений: tools/contrast.py — пересчёт при каждом изменении.
 */

export const palette = {
  // Базовые поверхности
  canvas: '#F5EFE0',
  panel: '#FBF6E8',
  panelRaised: '#FFFDF5',
  panelSunken: '#EFE7D4',

  // Акценты — поверхности (НЕ для текста)
  accentSurface: '#D4B896',
  accentSurfaceHover: '#C2A47E',
  accentSurfaceActive: '#AE9066',
  secondarySurface: '#C9B896',

  // Акценты — текст (проходят WCAG)
  accentText: '#7A5C30',        // 5.38:1 на canvas — AA
  accentTextStrong: '#6B4F28',  // 6.60:1 на canvas — AAA
  accentTextMuted: '#866738',   // 4.56:1 на canvas — AA

  // Текст
  textPrimary: '#3A3428',   // 10.76:1 — AAA
  textSecondary: '#6B6250', // 5.25:1 — AA
  textDisabled: '#A79C86',  // только для неинтерактивных элементов

  // Границы и разделители
  border: 'rgba(58, 52, 40, 0.08)',
  borderStrong: 'rgba(58, 52, 40, 0.16)',
  borderFocus: '#7A5C30',

  // Служебные — значения подобраны под порог 4.5:1 на canvas
  success: '#58754B', // 4.51:1 — AA
  warning: '#8A652D', // 4.60:1 — AA
  danger: '#A4503C',  // 4.83:1 — AA
  info: '#596F83',    // 4.55:1 — AA

  /**
   * Текст на залитых кнопках.
   * Кнопки светлые (песочные), поэтому текст на них тёмный, а не белый.
   * Белый на #D4B896 даёт 1.7:1 — нечитаемо.
   */
  onAccentSurface: '#3A3428',        // 6.52:1 на #D4B896 — AA
  onAccentSurfaceHover: '#3A3428',   // 5.23:1 на #C2A47E — AA
  onAccentSurfaceActive: '#241F16',  // 5.44:1 на #AE9066 — AA
  onAccentText: '#F5EFE0',           // 5.38:1 на #7A5C30 — AA
} as const;

/**
 * Типографическая шкала. Интервал 1.25 (major third third).
 * Семейство — только самохостинговый Inter (SIL OFL), ТЗ п.5.2.
 * Подключение fonts.googleapis.com запрещено (ТЗ п.10.1).
 */
export const typography = {
  fontFamily:
    "'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMono: "'JetBrains Mono', 'Consolas', monospace",

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
 * Тени. Два слоя: ближний контакт + дальний ореол.
 * Порядок в box-shadow: от ближнего к дальнему.
 */
export const shadows = {
  none: 'none',
  sm: '0 1px 2px rgba(212, 184, 150, 0.12)',
  md: '0 2px 8px rgba(212, 184, 150, 0.12)',
  lg: '0 8px 24px rgba(212, 184, 150, 0.16)',
  xl: '0 16px 48px rgba(212, 184, 150, 0.20)',
} as const;

/**
 * Эффекты Aura и Backlight (ТЗ п.5.2).
 * Период анимации «дыхания» — 4 секунды.
 */
export const effects = {
  /** Свечение вокруг активного элемента. Двухслойное. */
  aura: {
    near: '0 0 0 1px rgba(212, 184, 150, 0.5)',
    far: '0 0 24px 4px rgba(212, 184, 150, 0.35)',
    strong: {
      near: '0 0 0 1px rgba(212, 184, 150, 0.7)',
      far: '0 0 32px 8px rgba(212, 184, 150, 0.45)',
    },
  },
  /** Свет за панелью. z-index: -1 ставится на самом элементе. */
  backlight: {
    glow: `radial-gradient(
      600px 300px at 50% 0%,
      rgba(212, 184, 150, 0.6) 0%,
      rgba(212, 184, 150, 0.2) 40%,
      transparent 75%
    )`,
    blur: 'blur(45px)',
  },
  /** Анимация дыхания. Отключается при prefers-reduced-motion. */
  pulse: {
    duration: '4s',
    easing: 'cubic-bezier(0.4, 0, 0.6, 1)',
    keyframes: `
      @keyframes aura-pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.75; transform: scale(1.04); }
      }
    `,
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
 * Слои. Холст занимает максимум экрана (ТЗ п.4.2), поэтому панели
 * накладываются, а не сдвигают холст.
 */
export const layers = {
  backlight: -1,
  canvas: 0,
  canvasContent: 10,
  canvasSelection: 20,
  canvasGuides: 30,
  floatingPalette: 100,
  bottomDock: 110,
  topBar: 120,
  drawer: 200,
  modal: 300,
  toast: 400,
  commandPalette: 500,
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
 * focusRing использует accentText, а не accentSurface: последний
 * невидим на песочном фоне.
 */
export const a11y = {
  focusRing: `0 0 0 2px ${palette.canvas}, 0 0 0 4px ${palette.borderFocus}`,
  focusRingOffset: '2px',
  minTargetSize: '44px', // WCAG 2.5.5 — целевой размер
  contrast: {
    text: 4.5,    // AA для обычного текста
    largeText: 3, // AA для текста от 18px или 14px полужирного
    ui: 3,        // AA для границ и состояний
  },
  reducedMotion: '@media (prefers-reduced-motion: reduce)',
} as const;

export const tokens = {
  palette,
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
