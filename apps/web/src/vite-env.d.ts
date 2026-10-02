/// <reference types="vite/client" />

/**
 * Виртуальный модуль с CSS-переменными. Отдаётся плагином
 * aurabuilder-tokens (apps/web/vite.config.ts) из docs/palette.json.
 */
declare module '@tokens' {
  const css: string;
  export default css;
}
