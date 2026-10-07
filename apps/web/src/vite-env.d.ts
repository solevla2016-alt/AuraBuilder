/// <reference types="vite/client" />

/**
 * Виртуальный модуль с CSS-переменными. Отдаётся плагином
 * aurabuilder-tokens (apps/web/vite.config.ts) из docs/palette.json.
 */
declare module '@tokens' {
  const css: string;
  export default css;
}

/**
 * Значения палитры по темам для JavaScript. Отдаётся плагином
 * aurabuilder-tokens (apps/web/vite.config.ts) из docs/palette.json.
 */
declare module 'virtual:aurabuilder-palette' {
  const palette: { light: Record<string, string>; dark: Record<string, string> };
  export default palette;
}
