/**
 * Замер веса первого экрана и LCP через Chrome DevTools Protocol.
 *
 * Без внешних пакетов: запускаем headless Chrome, подключаемся по WebSocket
 * вручную. Причина — ТЗ п.1.3 требует LCP < 1.5 с, а проверить это можно
 * только на реальном билде.
 *
 * Меряется прод-сборка (vite preview), а не dev-сервер: в dev HMR и
 * некорректные размеры чанков искажают результат.
 *
 * Запуск: node tools/measure-lcp.mjs [url]
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MiniWebSocket } from './minisocket.mjs';

const URL_TO_TEST = process.argv[2] ?? 'http://localhost:4173/';

const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];

async function findChrome() {
  for (const p of CHROME_CANDIDATES) {
    if (existsSync(p)) return p;
  }
  throw new Error('Chrome/Edge не найден: проверьте путь установки');
}

const profile = mkdtempSync(join(tmpdir(), 'ab-lcp-'));
const port = 9222 + Math.floor(Math.random() * 400);

const chrome = await findChrome();
const proc = spawn(
  chrome,
  [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--disable-extensions',
    '--window-size=1366,768',
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
process.on('SIGINT', () => {
  cleanup();
  process.exit(1);
});

/** Ждём готовности devtools. */
async function waitForDevtools() {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (res.ok) return await res.json();
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('devtools не поднялся');
}

/**
 * Обёртка над CDP: сопоставляет id команд с ответами.
 * Транспорт — tools/minisocket.mjs (в Node 20 нет глобального WebSocket).
 */
class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.on('message', (text) => {
      const msg = JSON.parse(text);
      if (msg.id !== undefined) {
        const p = this.pending.get(msg.id);
        if (p) {
          this.pending.delete(msg.id);
          msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
        }
      } else {
        this.events.push(msg);
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

const version = await waitForDevtools();
console.log(`браузер: ${version.Browser}\nцель:   ${URL_TO_TEST}\n`);

/**
 * Проверка цели до запуска браузера.
 *
 * Без неё инструмент молча измеряет страницу ошибки Chrome: у неё
 * есть свой <h1>, TTFB около нуля, и замер выглядит как отличный
 * результат — хотя редактор не открывался вовсе.
 */
async function assertTargetReachable() {
  try {
    const res = await fetch(URL_TO_TEST, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const html = await res.text();
    if (!html.includes('<div id="root">')) {
      throw new Error('в ответе нет #root — это не редактор');
    }
    return true;
  } catch (e) {
    console.error(
      `цель ${URL_TO_TEST} недоступна: ${e.message}.\n` +
        'Запустите сборку и предпросмотр: npm run build, затем npm run preview',
    );
    process.exit(2);
  }
}

await assertTargetReachable();

const cdp = await CDP.connect(version.webSocketDebuggerUrl);
const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target = targets.find((t) => t.id === targetId);

const page = await CDP.connect(target.webSocketDebuggerUrl);

await page.send('Page.enable');
await page.send('Runtime.enable');
await page.send('Network.enable');
await page.send('Performance.enable');
await page.send('Emulation.setDeviceMetricsOverride', {
  width: 1366,
  height: 768,
  deviceScaleFactor: 1,
  mobile: false,
});

// Сеть ограничиваем, чтобы цифры были близки к мобильному интернету,
// а не к localhost: без этого всё показывает мгновенную загрузку.
await page.send('Network.emulateNetworkConditions', {
  offline: false,
  latency: 150,
  downloadThroughput: (1.6 * 1024 * 1024) / 8,
  uploadThroughput: (750 * 1024) / 8,
});

// LCP не отдаётся через getEntriesByType: API отдаёт только значения,
// уже записанные PerformanceObserver'ом. Поэтому observer ставится
// ДО навигации и складывает отчёты в window.__lcp.
await page.send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    window.__lcp = 0;
    window.__lcpEl = '';
    try {
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          window.__lcp = e.startTime;
          const el = e.element;
          if (el) {
            const cls = String(el.className || '').split(' ')[0];
            window.__lcpEl = el.tagName.toLowerCase() + (cls ? '.' + cls : '');
          }
        }
      }).observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (e) { window.__lcpErr = String(e); }
  `,
});

await page.send('Page.navigate', { url: URL_TO_TEST });

// Ждём завершения загрузки и ещё немного, чтобы успел прийти LCP:
// он фиксируется позже load, когда браузер понял, что это главный элемент.
let metrics = null;
for (let i = 0; i < 60; i++) {
  await new Promise((r) => setTimeout(r, 250));
  const res = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const out = { lcp: window.__lcp || 0, lcpEl: window.__lcpEl || '', lcpErr: window.__lcpErr || '',
                    fcp: 0, dcl: 0, load: 0, ttfb: 0, transfer: 0, requests: 0, byType: {} };
      const nav = performance.getEntriesByType('navigation')[0];
      if (nav) {
        out.dcl = nav.domContentLoadedEventEnd;
        out.load = nav.loadEventEnd;
        out.ttfb = nav.responseStart;
      }
      const fcp = performance.getEntriesByType('paint').find(p => p.name === 'first-contentful-paint');
      if (fcp) out.fcp = fcp.startTime;
      const res = performance.getEntriesByType('resource');
      out.requests = res.length;
      for (const r of res) {
        out.transfer += r.transferSize || 0;
        const key = (r.name.match(/\\/assets\\/([^/]+?)(-[^/]*)?\\.js$/) || [])[0] || 'other';
        out.byType[key] = (out.byType[key] || 0) + (r.transferSize || 0);
      }
      return out;
    })()`,
  });
  metrics = res.result.value;
  if (metrics.load > 0 && metrics.lcp > 0 && i > 10) break;
}

const transferKb = (metrics.transfer / 1024).toFixed(1);

console.log('метрики (мобильная эмуляция: 1.6 Мбит/с, задержка 150 мс)');
console.log('-'.repeat(58));
console.log(`TTFB                ${metrics.ttfb.toFixed(0)} мс`);
console.log(`First Contentful   ${metrics.fcp.toFixed(0)} мс`);
console.log(`LCP                ${metrics.lcp.toFixed(0)} мс   ${metrics.lcpEl}`);
console.log(`DOMContentLoaded   ${metrics.dcl.toFixed(0)} мс`);
console.log(`Load               ${metrics.load.toFixed(0)} мс`);
console.log(`Запрошено всего    ${transferKb} КБ в ${metrics.requests} запросах`);
console.log('-'.repeat(58));

if (Object.keys(metrics.byType).length) {
  console.log('по файлам:');
  for (const [k, v] of Object.entries(metrics.byType).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${k.padEnd(34)} ${(v / 1024).toFixed(1)} КБ`);
  }
  console.log('-'.repeat(58));
}

if (metrics.lcpErr) {
  console.log(`ошибка наблюдателя LCP: ${metrics.lcpErr}`);
}

const BUDGET = 1500;
if (metrics.lcp > 0) {
  console.log(
    metrics.lcp <= BUDGET
      ? `LCP ${metrics.lcp.toFixed(0)} мс — укладывается в бюджет ${BUDGET} мс (ТЗ п.1.3)`
      : `LCP ${metrics.lcp.toFixed(0)} мс ПРЕВЫШАЕТ бюджет ${BUDGET} мс на ${(metrics.lcp - BUDGET).toFixed(0)} мс`,
  );
}
page.ws.close();
cleanup();
// Код возврата: 1, если LCP превышает бюджет ТЗ п.1.3 — чтобы CI падал.
process.exit(metrics.lcp > BUDGET ? 1 : 0);
