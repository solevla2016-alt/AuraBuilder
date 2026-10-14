/**
 * PWA в браузере: манифест, регистрация worker, офлайн.
 *
 * Отдельный пробник, а не проверка внутри screenshot-editor.mjs:
 * service worker работает по другому жизненному циклу, ему нужен
 * второй проход страницы и отключённая сеть, а редактор к этому
 * отношения не имеет.
 *
 * Запуск:
 *   python tools/check_pwa.py
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { MiniWebSocket } from './minisocket.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const url = process.argv[2] ?? 'http://127.0.0.1:8080/';
const TIMEOUT = 20000;

const CHROME_CANDIDATES = [
  process.env.CHROME,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean);

const chromeBinary = CHROME_CANDIDATES.find((path) => {
  try {
    return existsSync(path);
  } catch {
    return false;
  }
});
if (!chromeBinary) {
  console.error('Chrome не найден. Укажите путь в переменной CHROME.');
  process.exit(1);
}

const profile = mkdtempSync(join(tmpdir(), 'aurabuilder-pwa-'));
const port = 9300 + Math.floor(Math.random() * 500);

const chrome = spawn(chromeBinary, [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  'about:blank',
], { stdio: 'ignore' });

async function firstTarget() {
  const deadline = Date.now() + TIMEOUT;
  while (Date.now() < deadline) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page;
    } catch {
      /* ещё поднимается */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('браузер не ответил');
}
await firstTarget();

const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
const browserWs = new MiniWebSocket(version.webSocketDebuggerUrl);
await browserWs.connect();

let browserId = 0;
const browserPending = new Map();
browserWs.on('message', (raw) => {
  const msg = JSON.parse(raw);
  if (msg.id === undefined || !browserPending.has(msg.id)) return;
  const waiter = browserPending.get(msg.id);
  browserPending.delete(msg.id);
  clearTimeout(waiter.timer);
  msg.error ? waiter.reject(new Error(JSON.stringify(msg.error))) : waiter.resolve(msg.result);
});
const browserSend = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++browserId;
    const timer = setTimeout(() => reject(new Error('таймаут ' + method)), TIMEOUT);
    browserPending.set(id, { resolve, reject, timer });
    browserWs.send(JSON.stringify({ id, method, params }));
  });

const created = await browserSend('Target.createTarget', { url: 'about:blank' });
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.id === created.targetId);
const ws = new MiniWebSocket(page.webSocketDebuggerUrl);
await ws.connect();

let nextId = 0;
const pending = new Map();
ws.on('message', (raw) => {
  const msg = JSON.parse(raw);
  if (msg.id === undefined) return;
  const waiter = pending.get(msg.id);
  if (!waiter) return;
  pending.delete(msg.id);
  clearTimeout(waiter.timer);
  msg.error ? waiter.reject(new Error(JSON.stringify(msg.error))) : waiter.resolve(msg.result);
});

const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => reject(new Error('таймаут ' + method)), TIMEOUT);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });

await send('Page.enable');
await send('Runtime.enable');
await send('Network.enable');
send('Page.navigate', { url }).catch(() => {});
await new Promise((r) => setTimeout(r, 2000));

const evaluate = async (expression) => {
  const res = await send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true,
  });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text);
  return res.result?.value;
};

const checks = [];
const check = (name, pass, detail = '') => checks.push([name, Boolean(pass), detail]);

const link = await evaluate(
  "document.querySelector('link[rel=manifest]')?.getAttribute('href') ?? null",
);
check('страница ссылается на манифест', link === 'manifest.json', link ?? 'нет');

const manifestText = await evaluate(
  `fetch('manifest.json').then((r) => r.text()).catch(() => '')`,
);
let parsed = null;
try {
  parsed = JSON.parse(manifestText);
} catch {
  parsed = null;
}
check('манифест отдаётся и разбирается', parsed && parsed.name === 'Цветы',
  parsed ? parsed.name : manifestText.slice(0, 60));
check('в манифесте есть иконки', (parsed?.icons?.length ?? 0) >= 2);

// Регистрация worker занимает время: браузер ставит его после загрузки.
let registered = false;
for (let i = 0; i < 40 && !registered; i += 1) {
  registered = await evaluate(
    "navigator.serviceWorker.getRegistrations().then((r) => r.length > 0)",
  );
  if (!registered) await new Promise((r) => setTimeout(r, 500));
}
check('service worker зарегистрирован', registered);

const cacheState = await evaluate(
  "caches.keys().then((keys) => keys.filter((k) => k.startsWith('aurabuilder-')))",
);
check('кеш сборки создан', (cacheState ?? []).length > 0,
  (cacheState ?? []).join(', '));

// Офлайн: сеть выключается по-настоящему, а не подменяется ответом.
await send('Network.emulateNetworkConditions', {
  offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0,
});
await send('Page.reload', { ignoreCache: false });
await new Promise((r) => setTimeout(r, 2500));

const offlineTitle = await evaluate(
  "document.querySelector('h2, h1')?.textContent ?? document.title",
);
check('без сети страница открывается из кеша', !!offlineTitle,
  String(offlineTitle ?? '').slice(0, 40));

await send('Network.emulateNetworkConditions', {
  offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1,
});

ws.close();
browserWs.close();
chrome.kill();

console.log('');
let ok = true;
for (const [name, pass, detail] of checks) {
  if (!pass) ok = false;
  console.log(`  ${pass ? 'ок  ' : '!!  '}${name}${detail ? ` (${detail})` : ''}`);
}
process.exitCode = ok ? 0 : 1;