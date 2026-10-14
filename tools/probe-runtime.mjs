/**
 * Путь покупателя по собранному пакету с рантаймом.
 *
 * Зачем отдельный пробник: корзина, оформление и поиск работают только
 * втроём — файлы пакета, живой рантайм и браузер. Проверка в несколько
 * вызовов probe не годится: каждый запуск открывает новый браузер с
 * новой сессией, и корзина между проверками исчезает. Здесь весь путь
 * проходит в одной сессии, как его проходит покупатель.
 *
 * Запуск:
 *   python tools/check_runtime.py        # в одном окне: сайт и рантайм
 *   node tools/probe-runtime.mjs http://127.0.0.1:PORT/
 *
 * Проверки повторяют требования из docs/RUNTIME.md, а не устройство
 * клиента: если рантайм переедет на другой порт или поменяет разметку,
 * пробник должен это заметить.
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { MiniWebSocket } from './minisocket.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const url = process.argv[2] ?? 'http://127.0.0.1:8000/';
const TIMEOUT = 15000;

const profile = mkdtempSync(join(tmpdir(), 'aurabuilder-rt-'));
const port = 9200 + Math.floor(Math.random() * 500);

/*
 * Путь к Chrome разный на Windows и Linux, а проверка должна идти
 * и в локальном прогоне, и в CI. Переменная CHROME переопределяет всё:
 * на машине разработчика браузер может стоять не в стандартном месте.
 */
const CHROME_CANDIDATES = [
  process.env.CHROME,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  process.env.PUPPETEER_EXECUTABLE_PATH,
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/opt/google/chrome/chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/snap/bin/chromium',
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

const chrome = spawn(chromeBinary, [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  'about:blank',
], { stdio: 'ignore' });

const cleanup = () => {
  try {
    chrome.kill();
  } catch {
    /* уже закрыт */
  }
  mkdirSync(profile, { recursive: true });
};
process.on('exit', cleanup);

/* --- браузер --------------------------------------------------------- */

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
send('Page.navigate', { url }).catch(() => {});
await new Promise((r) => setTimeout(r, 1500));

const evaluate = async (expression) => {
  const res = await send('Runtime.evaluate', { expression, returnByValue: true });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text);
  return res.result?.value;
};

async function waitFor(expression, what) {
  const deadline = Date.now() + TIMEOUT;
  while (Date.now() < deadline) {
    if (await evaluate(`!!(${expression})`)) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`не дождались: ${what}`);
}

async function click(selector) {
  const box = await evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    el.scrollIntoView({ block: 'center' });
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
  await new Promise((r) => setTimeout(r, 600));
}

async function typeInto(selector, value) {
  await evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
}

async function setCheckbox(selector) {
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  await new Promise((r) => setTimeout(r, 150));
}

const checks = [];
const check = (name, pass) => checks.push([name, Boolean(pass)]);

/* --- путь покупателя ------------------------------------------------- */

await waitFor("document.querySelector('.rt-cart')", 'блока корзины');

check(
  'заглушка скрыта, рабочий блок показан',
  (await evaluate(`(() => {
    const cart = document.querySelector('.rt-cart');
    const placeholder = document.querySelector('.rt-placeholder');
    return cart && !cart.hidden && placeholder && placeholder.hidden;
  })()`)),
);

check(
  'каталог дал кнопки с идентификаторами товаров',
  (await evaluate(
    "document.querySelectorAll('[data-rt-add]').length >= 3 &&"
    + " !!document.querySelector('[data-rt-add=\"t1\"]')",
  )),
);

await click('[data-rt-add="t1"]');
await waitFor("document.querySelector('.rt-cart__row')", 'позиции в корзине');
check(
  'товар добавлен в корзину',
  (await evaluate(
    "document.querySelector('.rt-cart__row').textContent.includes('Роза')",
  )),
);

await click('.rt-cart__row .rt-btn:last-child');
await waitFor(
  "document.querySelector('.rt-cart__total-value').textContent.includes('2')",
  'увеличенного количества',
);
const afterPlus = await evaluate(
  "document.querySelector('.rt-cart__total-value').textContent",
);
check(`количество увеличено (${afterPlus})`, afterPlus.includes('2'));

// Поиск: запрос не должен требовать отдельного нажатия.
await typeInto('.rt-search input[name="q"]', 'тюльпан');
await click('.rt-search button[type="submit"]');
await waitFor(
  "document.querySelector('.rt-search__results').textContent.includes('Тюльпан')",
  'результата поиска',
);
check(
  'поиск находит товар по запросу',
  await evaluate(
    "document.querySelector('.rt-search__results').textContent.includes('Тюльпан')",
  ),
);

// Оформление без согласия приниматься не должно. Проверяется не текст
// подсказки, а результат: браузер сам не отправит форму с
// неотмеченным обязательным согласием, и собственное сообщение
// клиента может не появиться вовсе.
await typeInto('.rt-form input[name="name"]', 'Ирина');
await typeInto('.rt-form input[name="phone"]', '+7 900 000-00-00');
await click('.rt-form button[type="submit"]');
check(
  'без согласия заказ не принят',
  !(await evaluate(
    "document.querySelector('.rt-form .rt-note').textContent.includes('Заказ №')",
  )),
);

await setCheckbox('.rt-form input[name="consent"]');
await click('.rt-form button[type="submit"]');
await waitFor(
  "document.querySelector('.rt-form .rt-note').textContent.includes('Заказ')",
  'номера заказа',
);
const order = await evaluate(
  "document.querySelector('.rt-form .rt-note').textContent",
);
check(`заказ принят (${order})`, order.includes('Заказ №'));

await waitFor(
  "document.querySelector('.rt-cart__total-value').textContent === '0 ₽'",
  'очищенной корзины',
);
check('корзина очищена после заказа', true);

const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(join(root, 'runtime-site.png'), Buffer.from(shot.data, 'base64'));

ws.close();
browserWs.close();
cleanup();

console.log('');
let ok = true;
for (const [name, pass] of checks) {
  if (!pass) ok = false;
  console.log(`  ${pass ? 'ок  ' : '!!  '}${name}`);
}
console.log('\nснимок: runtime-site.png');
process.exitCode = ok ? 0 : 1;
