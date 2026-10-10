/**
 * Шкалы дизайн-системы: отступы, радиусы, тени, слои, анимация,
 * типографика, сетка холста и требования доступности.
 *
 * Файл существует потому, что эти значения нужны в трёх местах: в
 * CSS-переменных для редактора, в документации и в проверках. Когда
 * они лежали в docs/design-tokens.ts, появились две правды: файл
 * дублировал их вручную, а значения разошлись с CSS — например,
 * радиуса round в токенах не было, а в шкале документации был.
 *
 * Направление одно: источник здесь, остальное генерируется.
 * Правка вручную в docs/design-tokens.ts или в CSS-переменных
 * перезаписывается следующей сборкой.
 */

export const typography = {
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMono: "'JetBrains Mono', 'SF Mono', Consolas, monospace",
  scale: {
    xs: { size: '0.75rem', lineHeight: 1.333, weight: 500 },
    sm: { size: '0.875rem', lineHeight: 1.429, weight: 400 },
    base: { size: '1rem', lineHeight: 1.5, weight: 400 },
    md: { size: '1.125rem', lineHeight: 1.5, weight: 500 },
    lg: { size: '1.375rem', lineHeight: 1.333, weight: 600 },
    xl: { size: '1.75rem', lineHeight: 1.286, weight: 600 },
    '2xl': { size: '2.25rem', lineHeight: 1.222, weight: 700 },
    '3xl': { size: '3rem', lineHeight: 1.167, weight: 700 },
  },
};

/** Отступы. Кратны четырём — сетка холста опирается на шаг 8. */
export const spacing = {
  xs: '4px',
  sm: '8px',
  md: '12px',
  lg: '16px',
  xl: '24px',
  '2xl': '32px',
  '3xl': '48px',
  '4xl': '64px',
  '5xl': '96px',
};

export const radii = {
  sm: '4px',
  md: '8px',
  lg: '12px',
  xl: '16px',
  pill: '999px',
  round: '50%',
};

export const shadows = {
  none: 'none',
  sm: '0 1px 2px rgba(15, 16, 18, 0.06)',
  md: '0 2px 8px rgba(15, 16, 18, 0.08)',
  lg: '0 8px 24px rgba(15, 16, 18, 0.12)',
  xl: '0 16px 48px rgba(15, 16, 18, 0.16)',
};

/**
 * Слои. Компактная шкала: холст 0–4, панели 10–12, оверлеи 20–50.
 * В шаблонах z-index достигал 16 — здесь сознательно меньше,
 * чтобы порядок наложения оставался читаемым.
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
};

/**
 * Анимация. Длительности короткие намеренно: редактор — рабочий
 * инструмент, и анимация здесь не украшение, а объяснение, что
 * произошло. Всё, что не несёт смысла, отключается при
 * prefers-reduced-motion.
 */
export const motion = {
  easing: {
    standard: 'cubic-bezier(0.2, 0, 0, 1)',
    decelerate: 'cubic-bezier(0, 0, 0.2, 1)',
    accelerate: 'cubic-bezier(0.4, 0, 1, 1)',
    emphasized: 'cubic-bezier(0.2, 0, 0, 1.2)',
  },
  duration: {
    fast: '120ms',
    base: '200ms',
    slow: '320ms',
  },
  reducedMotion: '@media (prefers-reduced-motion: reduce)',
};

/**
 * Свечение. Разрешено только там, где идёт действие: перетаскивание
 * блока и работа AI-ассистента. Постоянный декоративный ореол мешал бы
 * оценивать чужой дизайн — ровно то, ради чего существует редактор.
 */
export const effects = {
  auraDragging: { near: '0 0 0 1px rgba(217, 164, 65, 0.9)', far: '0 0 24px 4px rgba(217, 164, 65, 0.35)' },
  auraActive: { near: '0 0 0 1px rgba(217, 164, 65, 0.6)', far: '0 0 16px 2px rgba(217, 164, 65, 0.22)' },
  backlightGlow:
    'radial-gradient(600px 300px at 50% 0%, rgba(217, 164, 65, 0.28) 0%, rgba(217, 164, 65, 0.10) 40%, transparent 75%)',
  pulseDuration: '2.4s',
};

export const canvas = {
  gridSize: 8,
  snapThreshold: 4,
  breakpoints: { mobile: 360, tablet: 768, desktop: 1024, wide: 1440 },
  devices: {
    mobile: { width: 375, label: 'Mobile' },
    tablet: { width: 768, label: 'Tablet' },
    desktop: { width: 1280, label: 'Desktop' },
  },
};

/** Пороги WCAG 2.1, на которые опирается проверка контраста. */
export const a11y = {
  minTargetSize: '44px',
  contrast: { text: 4.5, largeText: 3, ui: 3 },
};