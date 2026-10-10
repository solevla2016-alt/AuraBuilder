/**
 * Полная проверка перед отправкой правки. Тот же набор, что в CI.
 *
 * Шаги идут от дешёвых к дорогим: сначала генерируемые файлы и
 * лицензии (секунды), потом типы и сборка, и только в конце тесты.
 * Обратный порядок заставил бы ждать минуты, чтобы узнать о
 * расхождении токенов, которое видно сразу.
 *
 * Запуск: npm run verify
 *
 * Что не проверяется здесь: сборка образов, браузерные сценарии и
 * замер LCP. Первое требует Docker и занимает минуты, вторые —
 * поднятый стенд; всё это живёт в CI.
 */

import { connect } from 'node:net';
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const apps = join(root, 'apps');

const isWindows = process.platform === 'win32';

/**
 * npm — это npm.cmd на Windows, а Node 20 не запускает .cmd без оболочки
 * (запуск с exec-файлом отключён из соображений безопасности: аргументы
 * не должны попадать в командную строку как есть). Оболочка включается
 * только на Windows и только для npm: аргументы здесь свои, не пользовательские.
 */
function npmStep(name, args) {
  return { name, cmd: () => 'npm', args: () => args, shell: isWindows };
}

/** Python: переменная PYTHON, затем venv в репозитории, затем системный. */
function pythonBin() {
  if (process.env['PYTHON']) return process.env['PYTHON'];
  const candidates = [
    join(root, '.venv', 'Scripts', 'python.exe'),
    join(root, '.venv', 'bin', 'python'),
  ];
  for (const c of candidates) if (existsSync(c)) return c;
  return 'python';
}

/**
 * Переменные из .env подхватываются так же, как это делает compose.
 * Без этого `npm run verify` требовал бы вручную выставлять пароль
 * PostgreSQL, хотя на стенде он уже записан.
 */
function dotEnv() {
  const path = join(root, '.env');
  if (!existsSync(path)) return {};
  const out = {};
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    out[trimmed.slice(0, eq).trim()] = trimmed
      .slice(eq + 1)
      .trim()
      .replace(/^["']|["']$/g, '');
  }
  return out;
}

/**
 * Интерпретатор передаётся дальше через PYTHON: без этого проверка
 * SBOM смотрела бы в системный Python, где Django нет, и ругалась бы
 * «реестр неполон» на заведомо полном окружении. Реестр должен
 * описывать то же окружение, в котором идут тесты.
 */
const baseEnv = {
  ...dotEnv(),
  ...process.env,
  PYTHON: process.env['PYTHON'] ?? pythonBin(),
  PYTHONIOENCODING: 'utf-8',
};

const steps = [
  npmStep('Сгенерированные файлы', ['run', 'registry:check']),
  npmStep('Контраст палитры', ['run', 'tokens:contrast']),
  npmStep('Лицензии npm', ['run', 'licenses']),
  {
    name: 'Лицензии Python',
    cmd: () => pythonBin(),
    args: () => [join(root, 'tools', 'license_gate_py.py')],
  },
  npmStep('Реестр SBOM', ['run', 'sbom', '--', '--check']),
  npmStep('Типы фронтенда', ['run', 'typecheck']),
  {
    // Тесты идут с DEBUG=0, как в CI: так проверяется боевая
    // конфигурация. Но SECURE_SSL_REDIRECT при этом включился бы, и
    // запросы к API отвечали бы 301 на несуществующий https-хост —
    // редирект снимается только на время тестов.
    name: 'Тесты Control Plane',
    cmd: () => pythonBin(),
    args: () => ['manage.py', 'test', 'projects', 'accounts', 'data_sources', 'component_library'],
    cwd: apps,
    env: { DJANGO_DEBUG: '0', DJANGO_SECURE_SSL_REDIRECT: '0' },
  },
];

const failed = [];
let index = 0;

/*
 * Предварительная проверка базы. Без неё тесты падают по таймауту
 * подключения к PostgreSQL, и первое, что видит разработчик, — это
 * трассировка psycopg вместо подсказки «поднимите стенд».
 */
const dbHost = baseEnv['POSTGRES_HOST'] ?? '127.0.0.1';
const dbPort = Number(baseEnv['POSTGRES_PORT'] ?? 5432);
const dbUp = await new Promise((resolve) => {
  const socket = connect(
    { host: dbHost, port: dbPort },
    () => {
      socket.destroy();
      resolve(true);
    },
  );
  socket.on('error', () => {
    socket.destroy();
    resolve(false);
  });
  setTimeout(() => {
    socket.destroy();
    resolve(false);
  }, 2000);
});

if (!dbUp && !baseEnv['USE_SQLITE']) {
  console.error(`PostgreSQL недоступен на ${dbHost}:${dbPort}.`);
  console.error('Поднимите стенд: docker compose up -d db');
  process.exit(1);
}

for (const step of steps) {
  index += 1;
  console.log(`\n=== [${index}/${steps.length}] ${step.name} ===`);

  const result = spawnSync(step.cmd(), step.args(), {
    cwd: step.cwd ?? root,
    stdio: 'inherit',
    env: { ...baseEnv, ...(step.env ?? {}) },
    shell: step.shell ?? false,
  });

  if (result.error) {
    console.error(`не удалось запустить: ${result.error.message}`);
    failed.push(step.name);
    continue;
  }
  if (result.status !== 0) failed.push(step.name);
}

console.log('');
if (failed.length) {
  console.error('не прошли:');
  for (const f of failed) console.error(`  ${f}`);
  process.exit(1);
}

console.log('все проверки прошли');
console.log('');
console.log('Не проверено здесь, живёт в CI: сборка образов, браузерные сценарии, LCP.');
console.log('Браузерные сценарии вручную:');
console.log('  node tools/screenshot-editor.mjs http://127.0.0.1:8080/');