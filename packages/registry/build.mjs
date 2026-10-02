/**
 * Генерация кода реестра модулей из packages/registry/modules.json.
 *
 * Один источник — modules.json, который в свою очередь собирается из
 * docs/MODULE-CATALOG.md. Реестр нужен в двух местах: валидация на сервере
 * (apps/projects) и палитра модулей в редакторе (apps/web). Держать
 * список руками в обоих местах означало бы гарантированный рассинхрон,
 * поэтому он генерируется.
 *
 * Запуск:
 *   node packages/registry/build.mjs
 *   node packages/registry/build.mjs --check
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const check = process.argv.includes('--check');

const source = join(here, 'modules.json');
if (!existsSync(source)) {
  console.error(
    'modules.json отсутствует — запустите python tools/catalog_to_registry.py',
  );
  process.exit(1);
}

const registry = JSON.parse(readFileSync(source, 'utf8'));
const modules = registry.modules;

const BANNER = 'СГЕНЕРИРОВАНО — не править руками. Источник: packages/registry/modules.json';

/* ---------------------------------------------------------------- */
/*  Python                                                            */
/* ---------------------------------------------------------------- */

function renderPython() {
  const lines = [];
  lines.push('"""Реестр модулей редактора для Control Plane.');
  lines.push('');
  lines.push(`* ${BANNER}`);
  lines.push(' * Генератор: packages/registry/build.mjs');
  lines.push(' * Исходный документ: docs/MODULE-CATALOG.md');
  lines.push('');
  lines.push('Используется в двух местах: валидация дерева страницы и эндпоинт');
  lines.push('каталога модулей. Список намеренно заморожен в момент импорта —');
  lines.push('модули добавляются выпуском, а не правкой этого файла.');
  lines.push('"""');
  lines.push('');
  lines.push('from __future__ import annotations');
  lines.push('');
  lines.push('from dataclasses import dataclass');
  lines.push('');
  lines.push('');
  lines.push('@dataclass(frozen=True)');
  lines.push('class Module:');
  lines.push('    """Описание модуля редактора."""');
  lines.push('');
  lines.push('    id: str');
  lines.push('    name: str');
  lines.push('    category: str');
  lines.push('    category_label: str');
  lines.push('    kind: str');
  lines.push('    stages: tuple[int, ...]');
  lines.push('');
  lines.push('    @property');
  lines.push('    def min_stage(self) -> int:');
  lines.push('        """Ранний этап, на котором модуль доступен."""');
  lines.push('        return min(self.stages)');
  lines.push('');
  lines.push('');
  lines.push('CATEGORIES: tuple[dict[str, str], ...] = (');
  for (const c of registry.categories) {
    lines.push(`    {'code': '${c.code}', 'id': '${c.id}', 'label': '${c.label}'},`);
  }
  lines.push(')');
  lines.push('');
  lines.push('MODULES: tuple[Module, ...] = (');
  for (const m of modules) {
    const stages = m.stages.join(', ');
    lines.push(
      `    Module('${m.id}', '${m.name}', '${m.category}', '${m.categoryLabel}', ` +
        `'${m.kind}', (${stages},)),`,
    );
  }
  lines.push(')');
  lines.push('');
  lines.push('MODULES_BY_ID: dict[str, Module] = {m.id: m for m in MODULES}');
  lines.push('MODULE_IDS: frozenset[str] = frozenset(MODULES_BY_ID)');
  lines.push('');
  lines.push('#: Виды блока на холсте: от них зависит заливка в редакторе.');
  lines.push('KINDS: frozenset[str] = frozenset({m.kind for m in MODULES})');
  lines.push('');
  lines.push('');
  lines.push('def modules_for_stage(stage: int) -> tuple[Module, ...]:');
  lines.push('    """Модули, доступные на указанном этапе выпуска."""');
  lines.push('    return tuple(m for m in MODULES if stage in m.stages)');
  lines.push('');
  return lines.join('\n');
}

/* ---------------------------------------------------------------- */
/*  TypeScript                                                       */
/* ---------------------------------------------------------------- */

function renderTypeScript() {
  const lines = [];
  lines.push('/*');
  lines.push(` * ${BANNER}`);
  lines.push(' * Генератор: packages/registry/build.mjs');
  lines.push(' * Исходный документ: docs/MODULE-CATALOG.md');
  lines.push(' *');
  lines.push(' * Реестр приходит из Control Plane при старте редактора; этот файл');
  lines.push(' * нужен для офлайн-подсказок и для типов, чтобы палитра модулей');
  lines.push(' * работала и без сети.');
  lines.push(' */');
  lines.push('');
  lines.push("export type ModuleKind = 'section' | 'text' | 'media';");
  lines.push('');
  lines.push('export interface ModuleDef {');
  lines.push('  id: string;');
  lines.push('  name: string;');
  lines.push('  category: string;');
  lines.push('  categoryLabel: string;');
  lines.push('  kind: ModuleKind;');
  lines.push('  stages: number[];');
  lines.push('  minStage: number;');
  lines.push('}');
  lines.push('');
  lines.push('export interface CategoryDef {');
  lines.push('  code: string;');
  lines.push('  id: string;');
  lines.push('  label: string;');
  lines.push('}');
  lines.push('');
  lines.push(`export const MODULE_CATEGORIES: CategoryDef[] = [`);
  for (const c of registry.categories) {
    lines.push(`  { code: '${c.code}', id: '${c.id}', label: '${c.label}' },`);
  }
  lines.push('];');
  lines.push('');
  lines.push(`export const MODULES: ModuleDef[] = [`);
  for (const m of modules) {
    lines.push(
      `  { id: '${m.id}', name: '${m.name}', category: '${m.category}', ` +
        `categoryLabel: '${m.categoryLabel}', kind: '${m.kind}', ` +
        `stages: [${m.stages.join(', ')}], minStage: ${m.minStage} },`,
    );
  }
  lines.push('];');
  lines.push('');
  lines.push('export const MODULE_IDS: ReadonlySet<string> = new Set(');
  lines.push('  MODULES.map((m) => m.id),');
  lines.push(');');
  lines.push('');
  lines.push('/** Модули, доступные на этапе выпуска. */');
  lines.push('export function modulesForStage(stage: number): ModuleDef[] {');
  lines.push('  return MODULES.filter((m) => m.stages.includes(stage));');
  lines.push('}');
  lines.push('');
  lines.push('export function moduleById(id: string): ModuleDef | undefined {');
  lines.push('  return MODULES.find((m) => m.id === id);');
  lines.push('}');
  lines.push('');
  lines.push('/**');
  lines.push(' * Вид блока на холсте. Заливка в редакторе берётся отсюда.');
  lines.push(' * Не путать с категорией каталога: data.list — категория data,');
  lines.push(' * но рисуется как текстовый блок.');
  lines.push(' */');
  lines.push('export function kindOf(moduleId: string): ModuleKind {');
  lines.push("  return moduleById(moduleId)?.kind ?? 'text';");
  lines.push('}');
  lines.push('');
  return lines.join('\n');
}

/* ---------------------------------------------------------------- */

const targets = [
  {
    path: join(root, 'apps/projects/module_registry.py'),
    content: renderPython(),
    label: 'Python',
  },
  {
    path: join(root, 'apps/web/src/ui/moduleRegistry.ts'),
    content: renderTypeScript(),
    label: 'TypeScript',
  },
];

if (check) {
  const stale = [];
  for (const t of targets) {
    if (!existsSync(t.path)) {
      stale.push(`${t.label}: файл отсутствует`);
      continue;
    }
    if (readFileSync(t.path, 'utf8') !== t.content) {
      stale.push(`${t.label}: разошёлся с modules.json`);
    }
  }
  if (stale.length) {
    console.error('Сгенерированный реестр устарел:');
    for (const s of stale) console.error('  ' + s);
    console.error('Запустите: npm run registry:build');
    process.exit(1);
  }
  console.log(`реестр актуален: модулей ${modules.length}, файлов ${targets.length}`);
  process.exit(0);
}

for (const t of targets) {
  mkdirSync(dirname(t.path), { recursive: true });
  writeFileSync(t.path, t.content, 'utf8');
  console.log(`written: ${t.path} (${t.label})`);
}
console.log(`модулей: ${modules.length}`);
