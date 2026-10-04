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

// Порядок важен: сначала системный браузер, которым пользуется
// разработчик, потом Chrome, потом Edge. В CI (ubuntu-latest)
// предустановлен google-chrome-stable, и он должен найтись первым.
const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  // Linux
  '/usr/bin/google-chrome-stable',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
  // macOS
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  // Windows
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);

function findChrome() {
  for (const p of CHROME_CANDIDATES) if (existsSync(p)) return p;
  throw new Error(
    'Chrome/Edge не найден. Задайте путь в переменной CHROME_PATH.',
  );
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
/**
 * Сценарии проверки редактора.
 *
 * getImageData из контекста Konva отдаёт буфер, не совпадающий с тем, что
 * видно на экране, поэтому состояние проверяется через DOM: приложение
 * выставляет data-атрибуты, которые невозможно «нарисовать».
 */
async function runScenarios(page, box) {
  const results = [];
  const state = async () => {
    const r = await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `(() => {
        const holder = document.querySelector('.canvas');
        const props = document.querySelector('.props-panel');
        const input = document.querySelector('.prop__input');
        return {
          blocks: Number(holder?.dataset.blocks ?? -1),
          selected: holder?.dataset.selected ?? '',
          panelTitle: props?.querySelector('.props__title b')?.textContent ?? null,
          panelVisible: !!props?.querySelector('.props__group'),
          firstLabel: input?.value ?? null,
          undoDisabled: document.querySelector('[aria-label="Отменить"]')?.disabled ?? null,
        };
      })()`,
    });
    return r.result.value;
  };

  // Клик по центру верхнего блока на холсте.
  const clickOnBlock = async () => {
    await page.send('Input.dispatchMouseEvent', {
      type: 'mousePressed',
      x: Math.round(box.x + box.width / 2),
      y: Math.round(box.y + 120),
      button: 'left',
      clickCount: 1,
    });
    await page.send('Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      x: Math.round(box.x + box.width / 2),
      y: Math.round(box.y + 120),
      button: 'left',
      clickCount: 1,
    });
    await new Promise((r) => setTimeout(r, 400));
  };

  /**
 * Отправка горячей клавиши.
 *
 * Для сочетаний с Ctrl нужен rawKeyDown: при keyDown браузер сначала
 * пытается вставить символ, и событие с модификатором доходит до
 * обработчика не всегда.
 */
const key = async (letter, code, modifiers = 0) => {
  const common = {
    modifiers,
    windowsVirtualKeyCode: letter.toUpperCase().charCodeAt(0),
    code,
    key: letter,
  };
  await page.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...common });
  await page.send('Input.dispatchKeyEvent', { type: 'keyUp', ...common });
  await new Promise((r) => setTimeout(r, 350));
};

  const before = await state();
  results.push(['блоки загружены', before.blocks > 0]);

  await clickOnBlock();
  const justAfter = await state();
  await new Promise((r) => setTimeout(r, 900));
  const afterClick = await state();
  results.push(['клик выбирает блок', afterClick.selected !== '']);
  results.push(['выделение не слетает само', afterClick.selected === justAfter.selected]);
  results.push(['панель свойств открыта', afterClick.panelVisible && !!afterClick.panelTitle]);

  // Меняем название блока через панель, затем отменяем.
  await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const inputs = [...document.querySelectorAll('.prop__input')];
      const text = inputs.find(el => el.type === 'text');
      if (!text) return { error: 'нет текстового поля' };
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(text, 'Изменённый заголовок');
      text.dispatchEvent(new Event('input', { bubbles: true }));
      return { ok: true, value: text.value, count: inputs.length };
    })()`,
  });
  await new Promise((r) => setTimeout(r, 600));
  const afterRename = await state();
  results.push(['название блока изменилось', afterRename.firstLabel === 'Изменённый заголовок']);
  results.push(['кнопка отмены активна', afterRename.undoDisabled === false]);

  // Пока фокус в поле ввода, Ctrl+Z должен отменять правку текста, а не
  // движение блока. Это осознанное поведение — снимаем фокус заранее.
  const renameTo = async (value) => {
    await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `(() => {
        const text = [...document.querySelectorAll('.prop__input')].find(el => el.type === 'text');
        if (!text) return false;
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, 'value').set;
        setter.call(text, ${JSON.stringify(value)});
        text.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      })()`,
    });
    await new Promise((r) => setTimeout(r, 450));
  };

  // Путь 1: кнопка в верхней панели.
  await renameTo('Правка через кнопку');
  const beforeButton = (await state()).firstLabel;
  await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const btn = document.querySelector('[aria-label="Отменить"]');
      if (!btn || btn.disabled) return false;
      btn.click();
      return true;
    })()`,
  });
  await new Promise((r) => setTimeout(r, 350));
  const afterButton = (await state()).firstLabel;
  results.push(['кнопка «Отменить» отменяет правку', afterButton !== 'Правка через кнопку']);
  void beforeButton;

  // Путь 2: горячая клавиша. Сначала проверяем, что она НЕ перехватывается
  // полем ввода: пока фокус в поле, Ctrl+Z отменяет правку текста.
  await renameTo('Правка через Ctrl+Z');
  await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const text = [...document.querySelectorAll('.prop__input')].find(el => el.type === 'text');
      if (!text) return false;
      text.focus();
      return document.activeElement === text;
    })()`,
  });
  await key('z', 'KeyZ', 2);
  const inField = await state();
  results.push([
    'в поле ввода Ctrl+Z не отменяет блок',
    inField.firstLabel === 'Правка через Ctrl+Z',
  ]);

  // Теперь снимаем фокус — отмена должна действовать на холст.
  await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      document.activeElement?.blur?.();
      return document.activeElement?.tagName ?? 'нет';
    })()`,
  });
  await new Promise((r) => setTimeout(r, 200));
  await key('z', 'KeyZ', 2);
  const afterUndo = await state();
  results.push(['Ctrl+Z отменяет правку блока', afterUndo.firstLabel !== 'Правка через Ctrl+Z']);

  // Выделение обязано пережить правки: иначе пользователь потерял бы
  // блок, который настраивал.
  results.push(['выделение сохраняется после правок', afterUndo.selected !== '']);

  // Содержимое текстового блока вводится через панель и должно появиться
  // на холсте. Берём блок text.*: у section.hero поля содержимого нет,
  // его наполняют данные на этапе 3.
  // Выбираем текстовый блок кликом ниже по холсту.
  await page.send('Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x: Math.round(box.x + box.width / 2),
    y: Math.round(box.y + 290),
    button: 'left',
    clickCount: 1,
  });
  await page.send('Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x: Math.round(box.x + box.width / 2),
    y: Math.round(box.y + 290),
    button: 'left',
    clickCount: 1,
  });
  await new Promise((r) => setTimeout(r, 500));

  // Правка содержимого попадает в дерево по blur поля. Без реального
  // фокуса blur не сработает и текст останется только в DOM — поэтому
  // фокусируем поле явно, а затем проверяем, что значение дошло до state.
  const typed = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const area = document.querySelector('.props__textarea');
      if (!area) return { error: 'нет поля содержимого' };
      area.focus();
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(area, 'Текст блока на холсте');
      area.dispatchEvent(new Event('input', { bubbles: true }));
      return { focused: document.activeElement === area };
    })()`,
  });
  await new Promise((r) => setTimeout(r, 300));

  // blur: поле теряет фокус, обработчик записывает правку в дерево.
  await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      document.activeElement?.blur?.();
      return true;
    })()`,
  });
  await new Promise((r) => setTimeout(r, 500));

  // Поле управляемое: после blur его значение приходит из state дерева.
  const contentValue = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const area = document.querySelector('.props__textarea');
      return area ? area.value : null;
    })()`,
  });
  const contentApplied = contentValue.result.value === 'Текст блока на холсте';

  results.push([
    'у текстового блока есть поле содержимого',
    !typed.result.value.error,
  ]);
  results.push(['правка содержимого доходит до дерева', contentApplied]);

  // Панель первого блока — section.hero, у которого есть схема свойств.
  // Переключаемся на него и проверяем, что поля отрисов��ются по
  // реестру, а не по общему списку.
  await page.send('Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x: Math.round(box.x + box.width / 2),
    y: Math.round(box.y + 120),
    button: 'left',
    clickCount: 1,
  });
  await page.send('Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x: Math.round(box.x + box.width / 2),
    y: Math.round(box.y + 120),
    button: 'left',
    clickCount: 1,
  });
  await new Promise((r) => setTimeout(r, 600));

  const schemaFields = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const ids = [...document.querySelectorAll('.props-panel [id^="prop-"]')].map(el => el.id);
      return { ids, hasSelect: !!document.querySelector('.props-panel select') };
    })()`,
  });
  const fields = schemaFields.result.value;
  results.push([
    'панель показывает поля схемы модуля',
    ['prop-heading', 'prop-buttonLabel', 'prop-background', 'prop-size'].every((id) =>
      fields.ids.includes(id),
    ),
  ]);
  results.push(['для select нарисованы варианты', fields.hasSelect]);

// Регрессия: автосохранение сбрасывало историю, и Ctrl+Z переставал
  // работать через секунду после правки — отмена пропадала ровно тогда,
  // когда пользователь возвращался к работе. Проверяем, что после
  // автоматического сохранения отмена жива.
  const typedLabel = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const input = document.querySelector('#block-label');
      if (!input) return { ok: false, why: 'поля нет' };
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value',
      ).set;
      setter.call(input, 'Проверка отмены после автосохранения');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return { ok: input.value === 'Проверка отмены после автосохранения' };
    })()`,
  });
  results.push([
    'панель дала изменить название блока',
    typedLabel.result.value?.ok === true,
  ]);

  // Ждём заведомо больше паузы автосохранения (1200 мс).
  await new Promise((r) => setTimeout(r, 2600));

  const saveLabel = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(document.querySelector('.save-state')?.textContent ?? '').trim()`,
  });
  results.push([
    'автосохранение сработало без Ctrl+S',
    saveLabel.result.value.includes('Сохранено'),
  ]);

  // Фокус с поля ввода нужно снять: иначе Ctrl+Z отменит правку
  // текста, а не действие редактора.
  await page.send('Runtime.evaluate', {
    expression: `document.activeElement?.blur?.()`,
  });
  await key('z', 'KeyZ', 2);
  await new Promise((r) => setTimeout(r, 500));

  const afterAutosaveUndo = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const el = document.querySelector('#block-label');
      return { has: !!el, value: el ? el.value : '' };
    })()`,
  });
  const undoProbe = afterAutosaveUndo.result.value ?? {};
  results.push([
    'Ctrl+Z работает после автосохранения',
    undoProbe.has && undoProbe.value !== 'Проверка отмены после автосохранения',
  ]);

  // Шрифт должен быть свой (ТЗ п.225, п.10.1) и реально применяться:
  // подключённый, но не загрузившийся Inter выглядит как системный
  // шрифт и внешних запросов не видно — ошибка проходит молча.
  const fontProbe = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const applied = getComputedStyle(document.body).fontFamily;
      const loaded = [...document.fonts].filter(f => f.status === 'loaded')
        .map(f => f.family + ' ' + f.weight);
      const wanted = [...document.fonts].filter(f => f.family === 'Inter')
        .map(f => f.status);
      return { applied, loaded, interCount: wanted.length, interLoaded: wanted.filter(s => s === 'loaded').length };
    })()`,
  });
  const font = fontProbe.result.value ?? {};
  results.push([
    'в стеке шрифтов есть Inter',
    String(font.applied ?? '').includes('Inter'),
  ]);
  results.push([
    `Inter реально загружен (${font.interLoaded} из ${font.interCount} начертаний)`,
    font.interLoaded > 0,
  ]);

  return results;
}

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

const checks = [
  ['холст найден', info.found],
  ['на холсте есть блоки', info.blocks > 0],
  ['холст не чёрный', stats ? stats.blackShare < 0.5 : false],
  ['на холсте видны разные цвета', stats ? stats.distinct >= 2 : false],
];

// Сценарии выполняются до закрытия сокета: они шлют команды в браузер.
// После cleanup() соединение уже разорвано и CDP отвечает таймаутом.
const scenarios = info.found ? await runScenarios(page, info.box) : [];

// Кадр после сценариев: на нём видны панель свойств и выделенный блок.
// Раньше снимок брался до сценариев и показывал пустую панель.
const shotAfter = await page.send('Page.captureScreenshot', { format: 'png' });
writeFileSync('editor-props.png', Buffer.from(shotAfter.data, 'base64'));

page.ws.close();
cleanup();

console.log('');
let ok = true;
for (const [name, pass] of [...checks, ...scenarios]) {
  if (!pass) ok = false;
  console.log(`  ${pass ? 'ок  ' : '!!  '}${name}`);
}

// Именно exitCode, а не process.exit: при перенаправлении вывода
// в файл process.exit обрывает асинхронную запись stdout, и часть
// строк (включая результаты проверок) теряется.
process.exitCode = ok ? 0 : 1;
