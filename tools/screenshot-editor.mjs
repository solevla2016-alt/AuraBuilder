/**
 * Снимок редактора и проверка, что холст действительно нарисован.
 *
 * Зачем это нужно: ошибка с цветами Konva (CSS-переменные вместо
 * значений) даёт чёрный прямоугольник, и в консоли браузера при этом
 * нет ни одной ошибки. Глазами в процессе разработки это легко
 * пропустить, а пользователь видит только чёрный экран.
 *
 * Скрипт берёт пиксели из центра canvas и сравнивает их с ожидаемыми:
 * холст не должен быть одноцветным чёрным.
 *
 * Запуск: node tools/screenshot-editor.mjs [url]
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MiniWebSocket } from './minisocket.mjs';
import { decodePng, regionStats } from './png.mjs';

const URL_TO_TEST = process.argv[2] ?? 'http://localhost:5173/';
const OUT = process.argv[3] ?? 'editor.png';

const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];

function findChrome() {
  for (const p of CHROME_CANDIDATES) if (existsSync(p)) return p;
  throw new Error('Chrome/Edge не найден');
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.console = [];
    ws.on('message', (text) => {
      const msg = JSON.parse(text);
      if (msg.id !== undefined) {
        const p = this.pending.get(msg.id);
        if (p) {
          this.pending.delete(msg.id);
          msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
        }
      } else {
        this.console.push(msg);
      }
    });
  }

  static async connect(url) {
    const ws = new MiniWebSocket(url);
    await ws.connect();
    return new CDP(ws);
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`таймаут ${method}`));
        }
      }, 30000);
    });
  }
}

const profile = mkdtempSync(join(tmpdir(), 'ab-shot-'));
const port = 9700 + Math.floor(Math.random() * 200);

const proc = spawn(
  findChrome(),
  [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--hide-scrollbars',
    '--window-size=1440,900',
    'about:blank',
  ],
  { stdio: 'ignore' },
);

const cleanup = () => {
  try {
    proc.kill();
  } catch {}
  try {
    rmSync(profile, { recursive: true, force: true });
  } catch {}
};
process.on('exit', cleanup);

let version = null;
for (let i = 0; i < 60 && !version; i++) {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/json/version`);
    if (res.ok) version = await res.json();
  } catch {
    await new Promise((r) => setTimeout(r, 250));
  }
}
if (!version) {
  console.error('devtools не поднялся');
  cleanup();
  process.exit(1);
}

const browser = await CDP.connect(version.webSocketDebuggerUrl);
const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' });
const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = await CDP.connect(list.find((t) => t.id === targetId).webSocketDebuggerUrl);

await page.send('Page.enable');
await page.send('Runtime.enable');
await page.send('Log.enable');
await page.send('Emulation.setDeviceMetricsOverride', {
  width: 1440,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
});

await page.send('Page.navigate', { url: URL_TO_TEST });
// Холст грузится лениво: ждём, пока он появится и отрисовался.
await new Promise((r) => setTimeout(r, 6000));

const probe = await page.send('Runtime.evaluate', {
  returnByValue: true,
  expression: `(() => {
    const canvases = [...document.querySelectorAll('.canvas canvas')];
    const holder = document.querySelector('.canvas');
    if (!canvases.length) return { found: false, canvases: 0 };
    const rect = canvases[0].getBoundingClientRect();
    return {
      found: true,
      canvases: canvases.length,
      width: canvases[0].width,
      height: canvases[0].height,
      blocks: Number(holder?.dataset.blocks ?? -1),
      // Координаты холста в пикселях страницы: по ним считаем статистику
      // прямо в снимке, а не в буфере Konva.
      box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      bg: getComputedStyle(document.body).backgroundColor,
    };
  })()`,
});

const shot = await page.send('Page.captureScreenshot', { format: 'png' });
const png = Buffer.from(shot.data, 'base64');
writeFileSync(OUT, png);

// Статистика берётся из самого снимка: буфер Konva через getImageData
// отдаёт данные, не совпадающие с тем, что видно на экране.
const info = probe.result.value;
let stats = null;
if (info.found) {
  const image = decodePng(png);
  stats = regionStats(image, info.box);
}

console.log('canvas:', JSON.stringify(info, null, 2));
console.log('пиксели холста:', JSON.stringify(stats));
console.log('снимок:', OUT);

const errors = page.console.filter(
  (m) =>
    (m.method === 'Log.entryAdded' && m.params?.entry?.level === 'error') ||
    m.method === 'Runtime.exceptionThrown',
);
if (errors.length) {
  console.log('\nОШИБКИ В КОНСОЛИ:');
  for (const e of errors.slice(0, 5)) {
    console.log(' ', e.params?.entry?.text ?? JSON.stringify(e.params ?? {}).slice(0, 200));
  }
}

page.ws.close();
cleanup();

const checks = [
  ['холст найден', info.found],
  ['на холсте есть блоки', info.blocks > 0],
  ['холст не чёрный', stats ? stats.blackShare < 0.5 : false],
  ['на холсте видны разные цвета', stats ? stats.distinct >= 2 : false],
];
console.log('');
let ok = true;
for (const [name, pass] of checks) {
  if (!pass) ok = false;
  console.log(`  ${pass ? 'ок  ' : '!!  '}${name}`);
}
process.exit(ok ? 0 : 1);
