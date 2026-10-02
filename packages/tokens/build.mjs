/**
 * Запись сгенерированных токенов в packages/tokens/dist/tokens.css.
 *
 * Файл нужен для:
 *   - предпросмотра палитры и статических страниц;
 *   - режима --check в CI.
 *
 * Vite при этом токены не читает: он получает их виртуальным модулем
 * (см. apps/web/vite.config.ts) — так dev-сервер не зависит от того,
 * успел ли отработать этот скрипт.
 *
 * Запуск:
 *   node packages/tokens/build.mjs
 *   node packages/tokens/build.mjs --check
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join } from 'node:path';
import { generateTokensCss, VARS } from './css.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, 'dist');
const outFile = join(outDir, 'tokens.css');

const check = process.argv.includes('--check');
const css = generateTokensCss();

if (check) {
  const current = existsSync(outFile) ? readFileSync(outFile, 'utf8') : null;
  if (current === css) {
    console.log('tokens.css актуален');
    process.exit(0);
  }
  console.error(
    current === null
      ? 'tokens.css отсутствует — запустите npm run tokens:build'
      : 'tokens.css разошёлся с docs/palette.json — запустите npm run tokens:build',
  );
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, css, 'utf8');
console.log(
  `written: ${outFile} (${VARS.length} переменных на тему, ${(css.length / 1024).toFixed(1)} КБ)`,
);
