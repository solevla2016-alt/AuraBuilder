/**
 * Проба страницы редактора из командной строки.
 *
 * Зачем она: пока разбираешь неожиданный экран, каждая проверка — это
 * одноразовый скрипт с копипастой CDP-обвязки. Их накопилось больше
 * десятка, и каждый следующий разбирающий вопрос начинался заново.
 *
 * Что делает: открывает страницу, при необходимости входит и печатает
 * результат выражения. Этого хватает на большинство разборов — что
 * на самом деле в DOM, куда ушёл запрос, что вернул сервер.
 *
 * Примеры:
 *
 *   node tools/probe.mjs http://127.0.0.1:8080/ --eval "document.querySelector('main').className"
 *   node tools/probe.mjs --login owner --password '...' --eval "localStorage.length"
 *   node tools/probe.mjs http://127.0.0.1:5173/ --wait .canvas canvas --click '[aria-label="Версии проекта"]'
 *   node tools/probe.mjs --open-project --eval "document.querySelectorAll('.vers__row').length"
 *   node tools/probe.mjs --file tools/probes/export.mjs
 *
 * Флаги:
 *   --url <адрес>       что открыть (по умолчанию http://127.0.0.1:8080/)
 *   --login <логин>     войти перед выражением
 *   --password <пароль> пароль (либо переменная PROBE_PASSWORD)
 *   --open-project      открыть первый проект из списка
 *   --wait <селектор>   ждать появления элемента
 *   --click <селектор>  кликнуть по элементу
 *   --text <селектор>   напечатать текст элемента
 *   --eval <выражение>  вычислить в странице и напечатать результат
 *   --file <путь>       выполнить скрипт-файл вместо --eval
 *   --timeout <мс>      сколько ждать браузер и элементы
 *   --shot <путь>       сохранить снимок экрана
 *   --keep              не закрывать браузер (для отладки вручную)
 */

import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
import { MiniWebSocket } from './minisocket.mjs';

/* --- разбор аргументов --- */

const args = process.argv.slice(2);
const flag = (name, fallback = null) => {
  const i = args.indexOf('--' + name);
  return i >= 0 && args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : fallback;
};
const has = (name) => args.includes('--' + name);
const positional = args.filter((a, i) => !a.startsWith('--') && !args[i - 1]?.startsWith('--'));

const URL_TO_OPEN = flag('url', positional[0] ?? 'http://127.0.0.1:8080/');
const TIMEOUT = Number(flag('timeout', '20000'));

/* --- поиск браузера --- */

const CHROME_CANDIDATES = [
  process.env['CHROME_PATH'],
  '/usr/bin/google-chrome-stable',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);

function findChrome() {
  for (const path of CHROME_CANDIDATES) {
    try {
      readFileSync(path);
      return path;
    } catch {
      // Следующий кандидат
    }
  }
  throw new Error('Chrome/Edge не найден. Задайте CHROME_PATH.');
}

/* --- браузер --- */

const port = 9300 + Math.floor(Math.random() * 300);
const chrome = spawn(
  findChrome(),
  [
    `--remote-debugging-port=${port}`,
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--window-size=1600,1000',
    '--user-data-dir=' + mkdtempSync(join(tmpdir(), 'ab-probe-')),
    'about:blank',
  ],
  { stdio: 'ignore' },
);

async function firstTarget() {
  const deadline = Date.now() + TIMEOUT;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page;
    } catch {
      // Браузер ещё поднимается
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('браузер не ответил');
}

await firstTarget();

// Подключение в два шага, как в screenshot-editor.mjs: сначала браузер
// (/json/version), затем созданная вкладка (/json/list). Соединение
// с вкладкой напрямую отвечало браузером, а страница молчала — все
// вызовы уходили в таймаут.
const version = await (await fetch('http://127.0.0.1:' + port + '/json/version')).json();
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
    const timer = setTimeout(() => {
      browserPending.delete(id);
      reject(new Error('таймаут ' + method));
    }, TIMEOUT);
    browserPending.set(id, { resolve, reject, timer });
    browserWs.send(JSON.stringify({ id, method, params }));
  });

const created = await browserSend('Target.createTarget', { url: 'about:blank' });
const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
const pageTarget = list.find((item) => item.id === created.targetId);
if (!pageTarget) throw new Error('вкладка не найдена');

const ws = new MiniWebSocket(pageTarget.webSocketDebuggerUrl);
await ws.connect();

let nextId = 0;
const pending = new Map();
const logs = [];

ws.on('message', (raw) => {
  const msg = JSON.parse(raw);
  if (msg.id !== undefined) {
    const waiter = pending.get(msg.id);
    if (waiter) {
      pending.delete(msg.id);
      clearTimeout(waiter.timer);
      msg.error ? waiter.reject(new Error(JSON.stringify(msg.error))) : waiter.resolve(msg.result);
    }
    return;
  }
  if (msg.method === 'Runtime.consoleAPICalled') {
    logs.push({
      kind: msg.params.type ?? 'log',
      text: (msg.params.args ?? [])
        .map((a) => a.value ?? a.description ?? '')
        .join(' ')
        .slice(0, 300),
    });
  } else if (msg.method === 'Runtime.exceptionThrown') {
    logs.push({
      kind: 'exception',
      text: (
        msg.params.exceptionDetails?.exception?.description ??
        msg.params.exceptionDetails?.text ??
        'исключение'
      ).slice(0, 300),
    });
  }
});

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`таймаут ${method}`));
    }, TIMEOUT);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

/**
 * Выражение с await.
 *
 * awaitPromise у Runtime.evaluate не работает: CDP возвращает незакрытый
 * промис, и в Node он выглядит как пустой объект. Результат поэтому
 * кладётся в window и читается следующим вызовом.
 */


/**
 * Выражение с await.
 *
 * awaitPromise у Runtime.evaluate не работает: CDP возвращает
 * незакрытый промис, и в Node он выглядит как пустой объект. Результат
 * кладётся в window и читается следующим вызовом.
 *
 * Маркер результата уникален на вызов. Общий window.__probe давал гонку:
 * выражение, обнуляющее маркер, ещё не успевало выполниться, а опрос
 * уже читал значение предыдущего вызова и возвращал его как своё.
 */
async function evalAsync(body) {
  const token = '__probe_' + Math.random().toString(36).slice(2);
  await send('Runtime.evaluate', {
    expression: `(() => {
      window.${token} = { pending: true };
      Promise.resolve().then(async () => {
        const value = await (async () => { ${body} })();
        window.${token} = { pending: false, value };
      }).catch((e) => { window.${token} = { pending: false, error: String(e) }; });
    })()`,
  });
  const deadline = Date.now() + TIMEOUT;
  while (Date.now() < deadline) {
    const res = await send('Runtime.evaluate', {
      returnByValue: true,
      expression: `JSON.stringify(window.${token} ?? null)`,
    });
    const parsed = res.result?.value ? JSON.parse(res.result.value) : null;
    if (parsed && parsed.pending === false) {
      if (parsed.error) throw new Error(parsed.error);
      return parsed.value;
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error('выражение не завершилось');
}

const evaluate = async (expression) => {
  const res = await send('Runtime.evaluate', { expression, returnByValue: true });
  return res.result?.value;
};

async function waitFor(selector, timeoutMs = TIMEOUT) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await evaluate(`!!document.querySelector(${JSON.stringify(normalizeSelector(selector))})`)) {
      return true;
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  return false;
}

async function click(selector) {
  const box = await evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(normalizeSelector(selector))});
    if (!el) return null;
    el.scrollIntoView({ block: 'center', inline: 'center' });
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  })()`);
  if (!box) throw new Error(`элемент не найден: ${selector}`);
  await send('Input.dispatchMouseEvent', {
    type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1,
  });
  await send('Input.dispatchMouseEvent', {
    type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1,
  });
  await new Promise((r) => setTimeout(r, 350));
}

/* --- селекторы --- */

/*
 * PowerShell съедает кавычки внутри аргумента: '[aria-label="X"]'
 * приходит как '[aria-label=X]'. Такой селектор в документе не
 * находится, и ошибка выглядит как «элемента нет», хотя он есть.
 * Значение атрибута дополняется кавычками здесь — иначе проба
 * нерабочая на той оболочке, на которой её и вызывают.
 */
function normalizeSelector(selector) {
  return selector.replace(
    /(\[[a-zA-Z-]+[~^$*|]?=)([^\]"\']+?)(?=\])/g,
    (_, head, value) => head + '"' + value.trim() + '"',
  );
}

/* --- сценарий --- */

await send('Page.enable');
await send('Runtime.enable');
// Навигация не ждёт ответа: Page.navigate у Chrome возвращает результат
// сразу, но при медленной загрузке сокет остаётся занят, и ожидание
// здесь превращается в таймаут там, где страница на самом деле
// открылась.
send('Page.navigate', { url: URL_TO_OPEN }).catch(() => {});
await new Promise((r) => setTimeout(r, 4000));

const login = flag('login');
if (login) {
  const password = flag('password') ?? process.env['PROBE_PASSWORD'];
  if (!password) throw new Error('нужен --password или PROBE_PASSWORD');
  const signedIn = await evalAsync(`
    const res = await fetch('/api/auth/login/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login: ${JSON.stringify(login)}, password: ${JSON.stringify(password)} }),
    });
    if (!res.ok) return { ok: false, status: res.status };
    const body = await res.json();
    localStorage.setItem('aurabuilder.access', body.access);
    localStorage.setItem('aurabuilder.refresh', body.refresh);
    return { ok: true };
  `);
  if (!signedIn?.ok) throw new Error(`вход не удался: ${signedIn?.status ?? '?'}`);
  await send('Page.reload', { ignoreCache: true });
  await new Promise((r) => setTimeout(r, 4000));
  console.log(`вошёл как ${login}`);
}

if (has('open-project')) {
  await waitFor('.dash__open');
  await click('.dash__open');
  await waitFor('.canvas canvas', TIMEOUT);
  await new Promise((r) => setTimeout(r, 1200));
  console.log('проект открыт');
}

const waitForSelector = flag('wait');
if (waitForSelector) {
  const ok = await waitFor(waitForSelector);
  console.log(ok ? `дождался ${waitForSelector}` : `НЕ дождался ${waitForSelector}`);
  if (!ok) process.exitCode = 1;
}

const clickSelector = flag('click');
if (clickSelector) {
  await click(clickSelector);
  console.log(`кликнул ${clickSelector}`);
}

const textSelector = flag('text');
if (textSelector) {
  const text = await evaluate(
    `(document.querySelector(${JSON.stringify(textSelector)})?.textContent ?? '').trim()`,
  );
  console.log(text || '(пусто)');
}

const expression = flag('eval');
const file = flag('file');
try {
  if (file) {
    const body = readFileSync(file, 'utf8');
    const value = await evalAsync(body);
    console.log(JSON.stringify(value, null, 2));
  } else if (expression) {
    const value = await evaluate(expression);
    console.log(JSON.stringify(value, null, 2));
  }
} catch (e) {
  console.error('ошибка выражения:', e.message);
  process.exitCode = 1;
}

const shot = flag('shot');
if (shot) {
  const { writeFileSync } = await import('node:fs');
  const image = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(shot, Buffer.from(image.data, 'base64'));
  console.log(`снимок: ${shot}`);
}

if (logs.length) {
  console.log('\nконсоль страницы:');
  for (const line of logs.slice(-15)) console.log(`  [${line.kind}] ${line.text}`);
}

if (!has('keep')) {
  ws.close();
  chrome.kill();
  process.exit(process.exitCode ?? 0);
} else {
  console.log(`\nбраузер оставлен. Отладка: http://127.0.0.1:${port}`);
}