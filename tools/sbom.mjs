/**
 * Реестр SBOM (ТЗ п.0.7): перечень всех зависимостей в стандартном
 * формате CycloneDX 1.6, генерируется на релиз.
 *
 * Зачем: лицензионный gate (ТЗ п.7.1.6, п.15.1) проверяет нарушение
 * в момент сборки, но не отвечает на вопрос «что именно попало в
 * поставку». SBOM — это перечень составом, который можно передать
 * заказчику вместе с релизом и который не меняется задним числом.
 *
 * Формат выбран CycloneDX, а не SPDX: он описывает зависимости с
 * указанием лицензии и происхождения (purl) в одном документе, а
 * SPDX для этого потребовал бы второго файла. Генератор свой, без
 * Syft и прочих внешних инструментов: они тянут базы уязвимостей из
 * внешних сервисов, а это отдельное нерешённое решение (ТЗ-GAPS,
 * п.0.4). Состав зависимостей известен из lock-файлов.
 *
 * Что попадает в реестр:
 *   * npm — из package-lock.json (там есть лицензия и resolved);
 *   * Python — из установленного окружения, версия сверяется с
 *     apps/requirements.txt, чтобы в реестр не попал лишний пакет
 *     из 开发者ской машины.
 *
 * Запуск: npm run sbom           (записать docs/sbom.json)
 *         npm run sbom -- --check  (сверить с записанным, ничего не писать)
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const OUT = join(root, 'docs', 'sbom.json');

/**
 * Пакеты внутри monorepo в реестр не идут: это исходники самой
 * платформы, а не зависимости. Но их состав перечислить нужно —
 * иначе в SBOM не видно, что аудитор приложит CodeFact.
 */
const WORKSPACE_MARKERS = ['apps/', 'packages/'];

/**
 * Идентификатор пакета по purl. У имён со scope символ @ кодируется,
 * иначе получалось бы pkg:npm/types/react вместо pkg:npm/%40types/react,
 * и такой purl не совпал бы с тем, что ожидают сторонние разборщики.
 */
function purlNpm(name, version) {
  const scoped = name.startsWith('@');
  const parts = (scoped ? name.slice(1) : name).split('/');
  const encoded = parts
    .map((part, index) => encodeURIComponent(scoped && index === 0 ? `@${part}` : part))
    .join('/');
  return `pkg:npm/${encoded}@${version}`;
}

function purlPython(name, version) {
  return `pkg:pypi/${encodeURIComponent(name.toLowerCase())}@${encodeURIComponent(version)}`;
}

/** Стабильный purl компонента: одинаковый вход — одинаковый ref. */
function refFor(purl) {
  return 'pkg-' + createHash('sha256').update(purl).digest('hex').slice(0, 16);
}

/**
 * npm-состав из lock-файла. Берём только то, что попадёт в поставку:
 * dev-зависимости редактора в образы не копируются.
 */
function collectNpm() {
  const lockPath = join(root, 'package-lock.json');
  const components = [];
  const workspaces = [];
  if (!existsSync(lockPath)) return { components, workspaces };

  const lock = JSON.parse(readFileSync(lockPath, 'utf8'));
  const packages = lock.packages ?? {};

  for (const [path, entry] of Object.entries(packages)) {
    if (!path.startsWith('node_modules/')) continue;
    if (entry.dev) continue;

    // Имя пакета берётся по последнему node_modules/: у вложенных
    // копий путь вида node_modules/its-fine/node_modules/@types/react,
    // и срез от начала дал бы имя с путём внутри.
    const name = path.split('node_modules/').pop();
    const resolved = entry.resolved ?? '';
    // Локальная ссылка вида packages/tokens — это воркспейс, а не пакет.
    // Проверка идёт до проверки версии: у воркспейсов версии нет.
    if (!resolved.startsWith('http')) {
      if (resolved && WORKSPACE_MARKERS.some((m) => resolved.startsWith(m))) {
        workspaces.push({ name, path: resolved, license: entry.license ?? 'UNLICENSED' });
      }
      continue;
    }

    if (!entry.version) continue;

    components.push({
      type: 'library',
      name,
      version: entry.version,
      purl: purlNpm(name, entry.version),
      licenses: entry.license ? [{ license: { id: entry.license } }] : [],
      // Хеш берём из целостности lock-файла: это sha512 от tarball,
      // и он же служит доказательством происхождения пакета.
      hashes: entry.integrity
        ? [{ alg: 'SHA-512', content: entry.integrity.replace(/^sha512-/, '') }]
        : [],
      properties: [
        { name: 'aurabuilder:ecosystem', value: 'npm' },
        { name: 'aurabuilder:resolved', value: resolved },
      ],
    });
  }

  components.sort((a, b) => a.purl.localeCompare(b.purl));
  return { components, workspaces };
}

/**
 * Состав установленного окружения в JSON.
 *
 * Отдельный процесс с importlib.metadata, а не `pip show`: формат
 * --format=json появился не во всех версиях pip, а на машине
 * разработчика может оказаться любая. Скрипт на Python нужен ровно
 * один, дальше разбор идёт в Node.
 */
const PY_INVENTORY = `
import json, re
try:
    import importlib.metadata as md
except ImportError:
    import importlib_metadata as md

# Ключи нормализуются по PEP 503: djangorestframework_simplejwt из
# окружения и djangorestframework-simplejwt из requirements.txt — одно
# и то же имя, и без нормализации пакет не находился.
def key(name):
    return re.sub(r'[-_.]+', '-', name).lower()

# Идентификатор лицензии берётся сначала из License-Expression (PEP 639),
# потом из License, и только потом из классификаторов: у Django, DRF и
# psycopg поле License пустое, а лицензия указана именно в classifiers.
def licence(meta):
    expr = meta['License-Expression']
    if expr and len(expr) <= 60:
        return expr
    plain = meta['License']
    if plain and len(plain) <= 60 and '\\n' not in plain:
        return plain
    for c in meta.get_all('Classifier') or []:
        if c.startswith('License ::'):
            tail = c.rsplit(' :: ', 1)[-1]
            if tail in ('MIT License', 'BSD License', 'Apache Software License'):
                return {'MIT License': 'MIT', 'BSD License': 'BSD-3-Clause',
                        'Apache Software License': 'Apache-2.0'}[tail]
    return None

out = {}
for dist in md.distributions():
    name = dist.metadata['Name']
    if not name:
        continue
    out[key(name)] = {'version': dist.version, 'license': licence(dist.metadata)}
print(json.dumps(out))
`;

function pythonInventory() {
  try {
    const raw = execFileSync(process.env['PYTHON'] ?? 'python', ['-c', PY_INVENTORY], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      maxBuffer: 16 * 1024 * 1024,
    });
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Python-состав. Список прямых зависимостей берётся из requirements.txt,
 * а версии и лицензии — из установленного окружения.
 *
 * Так состав не зависит от машины: если в venv д��жали лишнего
 * (например, IPython при отладке), в реестр он не попадёт. Пакет из
 * requirements.txt, которого в окружении нет, — расхождение, и оно
 * должно обрывать проверку, а не молча пропускаться.
 */
function collectPython() {
  const requirementsPath = join(root, 'apps', 'requirements.txt');
  const components = [];
  const missing = [];
  if (!existsSync(requirementsPath)) return { components, missing };

  const installed = pythonInventory();

  const required = readFileSync(requirementsPath, 'utf8')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))
    .map((line) => {
      const m = line.match(/^([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9._-]+)$/);
      return m ? { name: m[1], version: m[2] } : null;
    })
    .filter(Boolean);

  for (const { name, version } of required) {
    // Ключи окружения нормализованы по PEP 503: psycopg[binary]
    // из requirements.txt и psycopg из importlib.metadata — одно и то же.
    const found = installed?.[name.toLowerCase().replace(/[-_.]+/g, '-')];
    if (!found) {
      missing.push({ name, version });
      continue;
    }

    const actual = found.version;
    const matches = actual === version;
    const licence = found.license ?? null;

    components.push({
      type: 'library',
      name,
      version: actual,
      purl: purlPython(name, actual),
      licenses: licence ? [{ license: { id: licence } }] : [],
      properties: [
        { name: 'aurabuilder:ecosystem', value: 'pypi' },
        { name: 'aurabuilder:pinned', value: version },
        ...(matches ? [] : [{ name: 'aurabuilder:version-mismatch', value: version }]),
      ],
    });
  }

  components.sort((a, b) => a.purl.localeCompare(b.purl));
  return { components, missing };
}

function build() {
  const npm = collectNpm();
  const python = collectPython();

  const components = [...npm.components, ...python.components];
  for (const w of npm.workspaces) {
    components.push({
      type: 'application',
      name: w.name,
      version: '0.0.0',
      purl: purlNpm(w.name, '0.0.0'),
      licenses: [{ license: { id: w.license } }],
      properties: [
        { name: 'aurabuilder:ecosystem', value: 'npm' },
        { name: 'aurabuilder:workspace', value: w.path },
      ],
    });
  }

  const meta = {
    timestamp: new Date().toISOString(),
    tools: [{ vendor: 'AuraBuilder', name: 'tools/sbom.mjs', version: '1.0.0' }],
    component: {
      type: 'application',
      name: 'aurabuilder',
      version: readVersion(),
      licenses: [{ license: { id: 'UNLICENSED' } }],
    },
  };

  const doc = {
    bomFormat: 'CycloneDX',
    specVersion: '1.6',
    serialNumber: `urn:uuid:${serial()}`,
    version: 1,
    metadata: meta,
    components,
  };

  return { doc, python: python.missing, count: components.length };
}

function readVersion() {
  const pkgPath = join(root, 'package.json');
  if (!existsSync(pkgPath)) return '0.0.0';
  return JSON.parse(readFileSync(pkgPath, 'utf8')).version ?? '0.0.0';
}

/**
 * serialNumber обязан быть стабильным для одного и того же состава:
 * иначе при каждой генерации файл отличается побайтно и его невозможно
 * сравнивать глазами. Поэтому он выводится из состава, а не из времени.
 */
function serial() {
  const npm = collectNpm();
  const python = collectPython();
  const fingerprint = [...npm.components.map((c) => c.purl), ...python.components.map((c) => c.purl)]
    .sort()
    .join('\n');
  const hex = createHash('sha256').update(fingerprint).digest('hex');
  const uuid = [
    hex.slice(0, 8),
    hex.slice(8, 12),
    '4' + hex.slice(13, 16),
    ((parseInt(hex[16], 16) & 0x3) | 0x8).toString(16) + hex.slice(17, 20),
    hex.slice(20, 32),
  ].join('-');
  return uuid;
}

const CHECK = process.argv.includes('--check');
const { doc, python: missing, count } = build();

console.log(`компонентов: ${count} (npm: ${doc.components.filter((c) => (c.properties ?? []).some((p) => p.value === 'npm')).length}, pypi: ${doc.components.filter((c) => (c.properties ?? []).some((p) => p.value === 'pypi')).length})`);

if (missing.length) {
  console.error('\nПрямые зависимости не найдены в окружении:');
  for (const m of missing) console.error(`  ${m.name}==${m.version}`);
  console.error('\nРеестр неполон: поставьте зависимости или укажите путь к окружению через PYTHON.');
  process.exit(1);
}

const mismatched = doc.components.filter((c) =>
  (c.properties ?? []).some((p) => p.name === 'aurabuilder:version-mismatch'),
);
if (mismatched.length) {
  console.error('\nВерсия в окружении разошлась с requirements.txt:');
  for (const c of mismatched) {
    const pinned = c.properties.find((p) => p.name === 'aurabuilder:pinned')?.value;
    console.error(`  ${c.name}: установлена ${c.version}, закреплено ${pinned}`);
  }
  process.exit(1);
}

const serialised = JSON.stringify(doc, null, 2) + '\n';

if (CHECK) {
  if (!existsSync(OUT)) {
    console.error(`Реестр отсутствует: ${OUT}. Создайте его командой npm run sbom.`);
    process.exit(1);
  }
  const stored = readFileSync(OUT, 'utf8');
  if (stored === serialised) {
    console.log('реестр SBOM актуален');
    process.exit(0);
  }
  // Время генерации меняется при каждом запуске и само по себе не
  // является расхождением, поэтому сравнение идёт по составу.
  const strip = (text) => {
    const parsed = JSON.parse(text);
    delete parsed.metadata.timestamp;
    return JSON.stringify(parsed, null, 2);
  };
  if (strip(stored) === strip(serialised)) {
    console.log('состав SBOM актуален (отличается только время генерации)');
    process.exit(0);
  }
  console.error('состав SBOM разошёлся с записанным — обновите командой npm run sbom');
  process.exit(1);
}

writeFileSync(OUT, serialised, 'utf8');
console.log(`реестр записан: ${OUT}`);