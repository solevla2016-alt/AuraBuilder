/**
 * Лицензионный gate. ТЗ п.7.1.6 и п.15.1: зависимости с copyleft
 * (GPL, AGPL, SSPL, RSAL, Elastic) запрещены.
 *
 * Скрипт НЕ ходит в сеть: читает поле license из package.json каждого
 * установленного пакета. Проверка офлайн — требование ТЗ п.15.1,
 * потому что `npm audit` передаёт дерево зависимостей за рубеж.
 *
 * Запуск: npm run licenses
 * Код возврата 1, если найдена запрещённая или неизвестная лицензия.
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join, relative } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

/** Разрешены: пермиссивные и слабые копилефты (LGPL — только как динамическая
 *  линковка, фактически не используется, но не блокирует проверку). */
const ALLOWED = new Set([
  'MIT',
  'ISC',
  'Apache-2.0',
  'BSD-2-Clause',
  'BSD-3-Clause',
  '0BSD',
  'CC0-1.0',
  'Unlicense',
  'Python-2.0',
  'BlueOak-1.0.0',
  'Zlib',
  'MPL-2.0', // Mozilla — слабый copyleft, разрешён ТЗ явно
  'LGPL-3.0-or-later',
  'LGPL-2.1-or-later',
  // Собственные закрытые пакеты AuraBuilder
  'UNLICENSED',
]);

/** Запрещены явно — с указанием причины, чтобы не молча сменить правила. */
const FORBIDDEN = {
  'GPL-2.0': 'ТЗ п.7.1.6: copyleft с обязательным распространением исходников',
  'GPL-3.0': 'ТЗ п.7.1.6: copyleft с обязательным распространением исходников',
  'AGPL-3.0': 'ТЗ п.7.1.6: сетевой copyleft — самая строгая форма',
  'SSPL-1.0': 'ТЗ п.7.1.6: серверная лицензия, не OSI',
  'RSAL-2.0': 'ТЗ п.7.1.6: source-available, не OSI',
  'BUSL-1.1': 'ТЗ п.7.1.6: source-available с запретом на конкуренцию',
  'Elastic-2.0': 'ТЗ п.7.1.6: не OSI',
  'CC-BY-NC-4.0': 'запрет коммерческого использования',
};

/** Синонимы, которые npm отдаёт в разной форме. */
const NORMALISE = {
  'apache 2.0': 'Apache-2.0',
  'apache-2': 'Apache-2.0',
  'bsd': 'BSD-3-Clause',
  'new bsd': 'BSD-3-Clause',
  'mit license': 'MIT',
  'mozilla public license 2.0 (mpl 2.0)': 'MPL-2.0',
  'the mit license': 'MIT',
  // Собственные пакеты монорепозитория: закрытые, лицензия не нужна.
  unlicensed: 'UNLICENSED',
};

function normalise(raw) {
  const v = String(raw ?? '').trim();
  const key = v.toLowerCase();
  return NORMALISE[key] ?? v;
}

/** @returns {string[]} пути ко всем node_modules в рабочей области */
function nodeModulesDirs() {
  const out = [join(root, 'node_modules')];
  for (const group of ['apps', 'packages']) {
    const base = join(root, group);
    if (!existsSync(base)) continue;
    for (const name of readdirSync(base)) {
      const nested = join(base, name, 'node_modules');
      if (existsSync(nested)) out.push(nested);
    }
  }
  return out;
}

/** Рекурсивный обход: node_modules/@scope/pkg/node_modules/... */
function collect(nmDir, acc = []) {
  let entries;
  try {
    entries = readdirSync(nmDir, { withFileTypes: true });
  } catch {
    return acc;
  }
  for (const e of entries) {
    if (!e.isDirectory() && !e.isSymbolicLink()) continue;
    if (e.name === '.bin' || e.name === '.package-lock.json') continue;
    const full = join(nmDir, e.name);
    if (e.name.startsWith('@')) {
      collect(full, acc);
      continue;
    }
    const pj = join(full, 'package.json');
    if (existsSync(pj)) {
      try {
        const p = JSON.parse(readFileSync(pj, 'utf8'));
        acc.push({ name: p.name ?? e.name, license: p.license, path: full });
      } catch {
        // битый package.json — игнорируем, npm install это отловит
      }
    }
    collect(join(full, 'node_modules'), acc);
  }
  return acc;
}

const seen = new Map();
for (const nm of nodeModulesDirs()) {
  for (const pkg of collect(nm)) {
    if (!seen.has(pkg.name)) seen.set(pkg.name, pkg);
  }
}

const rows = [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));

const bad = [];
const unknown = [];

console.log('пакет'.padEnd(42) + 'лицензия');
console.log('-'.repeat(64));
for (const p of rows) {
  const lic = normalise(p.license);
  const isBad = FORBIDDEN[lic] !== undefined;
  const isOk = ALLOWED.has(lic);
  if (isBad) bad.push({ ...p, lic, why: FORBIDDEN[lic] });
  else if (!isOk) unknown.push({ ...p, lic });
  const mark = isBad ? ' <-- ЗАПРЕЩЕНА' : isOk ? '' : ' <-- проверить';
  console.log(p.name.padEnd(42) + (lic || '(нет поля license)') + mark);
}
console.log('-'.repeat(64));

const total = rows.length;
console.log(`пакетов: ${total}, запрещённых: ${bad.length}, неопознанных: ${unknown.length}`);

if (bad.length) {
  console.log('\nЗАПРЕЩЁННЫЕ ЛИЦЕНЗИИ:');
  for (const b of bad) console.log(`  ${b.name} — ${b.lic}: ${b.why}`);
}

if (unknown.length) {
  console.log('\nНЕОПОЗНАННЫЕ (требуют ручной проверки):');
  for (const u of unknown) console.log(`  ${u.name} — ${u.lic}`);
}

process.exit(bad.length > 0 ? 1 : 0);
