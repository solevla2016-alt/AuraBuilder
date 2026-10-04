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

/*
 * Вспомогательные функции для CDP. Объявлены до первой проверки,
 * потому что const не поднимается как функция: обращение к помощнику
 * выше по тексту давало бы «Cannot access before initialization».
 */

/** Перезагрузка страницы: нужна после входа и выхода. */
const reload = async (page) => {
  await page.send('Page.reload', { ignoreCache: true });
  await new Promise((r) => setTimeout(r, 2500));
};

/** Ожидание появления селектора. Возвращает false, если не дождались. */
const waitFor = async (page, selector, timeoutMs) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `!!document.querySelector(${JSON.stringify(selector)})`,
    });
    if (found.result.value) return true;
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
};

const has = (page, selector) =>
  page
    .send('Runtime.evaluate', {
      returnByValue: true,
      expression: `!!document.querySelector(${JSON.stringify(selector)})`,
    })
    .then((r) => r.result.value === true);

/**
 * Ввод значения в поле через нативный сеттер.
 *
 * Прямое input.value = ... не работает: React не видит изменения, и
 * контролируемое поле возвращает прежнее значение.
 */
const fill = async (page, selector, value) => {
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return;
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  });
  await new Promise((r) => setTimeout(r, 120));
};

/** Текст элемента или пустая строка. */
const text = async (page, selector) => {
  const res = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `((document.querySelector(${JSON.stringify(selector)})?.textContent ?? '').trim())`,
  });
  return res.result.value ?? '';
};

/** Клик по элементу через реальные координаты: React слушает указатель. */
const click = async (page, selector) => {
  const box = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    })()`,
  });
  const point = box.result.value;
  if (!point) throw new Error(`элемент не найден: ${selector}`);
  await page.send('Input.dispatchMouseEvent', {
    type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1,
  });
  await page.send('Input.dispatchMouseEvent', {
    type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1,
  });
};

/**
 * HTTP-запрос из страницы и чтение результата.
 *
 * awaitPromise в Runtime.evaluate здесь не работает: значение возвращается
 * в Node, и относительный адрес /api/... превращается в невалидный URL.
 * Поэтому запрос выполняется в странице, результат кладётся в window, а
 * следующим вызовом читается.
 */
const fetchFromPage = async (page, path, withAuth) => {
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      window.__probe = { pending: true };
      const headers = {};
      if (${withAuth ? 'true' : 'false'}) {
        headers['Authorization'] = 'Bearer ' + localStorage.getItem('aurabuilder.access');
      }
      fetch(${JSON.stringify('/api' + path)}, { headers })
        .then(async (res) => {
          const body = await res.text();
          let count = -1;
          try {
            const parsed = JSON.parse(body);
            count = Array.isArray(parsed) ? parsed.length : -1;
          } catch { /* ответ не JSON — достаточно кода */ }
          window.__probe = { pending: false, status: res.status, count };
        })
        .catch((e) => { window.__probe = { pending: false, status: 0, error: String(e) }; });
    })()`,
  });

  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const res = await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: 'JSON.stringify(window.__probe ?? null)',
    });
    const parsed = res.result.value ? JSON.parse(res.result.value) : null;
    if (parsed && parsed.pending === false) return parsed;
    await new Promise((r) => setTimeout(r, 200));
  }
  return { status: 0, count: -1, error: 'таймаут' };
};

/**
 * Асинхронное выражение в странице с надёжным ожиданием.
 *
 * awaitPromise у Runtime.evaluate здесь не работает: CDP возвращает
 * незакрытый промис, и в Node он выглядит как пустой объект. Поэтому
 * результат кладётся в window.__result и читается следующим вызовом.
 */
const evalAsync = async (page, body) => {
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      window.__result = { pending: true };
      Promise.resolve().then(async () => {
        const value = await (async () => {
          ${body}
        })();
        window.__result = { pending: false, value };
      }).catch((e) => {
        window.__result = { pending: false, error: String(e) };
      });
    })()`,
  });

  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const res = await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: 'JSON.stringify(window.__result ?? null)',
    });
    const parsed = res.result.value ? JSON.parse(res.result.value) : null;
    if (parsed && parsed.pending === false) {
      if (parsed.error) throw new Error(`ошибка в странице: ${parsed.error}`);
      return parsed.value;
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('выражение в странице не завершилось');
};

await page.send('Page.navigate', { url: URL_TO_TEST });
// Холст грузится лениво: ждём, пока он появится и отрисовался.
await new Promise((r) => setTimeout(r, 6000));

/*
 * Вход выполняется до всех остальных проверок.
 *
 * Редактор закрыт без токена (ТЗ п.11.1), поэтому сначала регистрация
 * и вход через API, а уже потом проба холста и сценарии. Форма входа
 * проверяется отдельно в конце: если бы проверялась только она, падение
 * сервера выглядело бы как «вход не работает».
 *
 * Пользователь создаётся один на прогон, а в следующих прогонах
 * переиспользуется по дате: иначе в базе копились бы десятки
 * «автопробных» пользователей.
 */
const authDay = new Date().toISOString().slice(0, 10).replaceAll('-', '');
const authUser = `autoprobe${authDay}`;
const authPassword = 'probepassword123';

const signIn = await evalAsync(page, `
    const post = (url, body) => fetch('/api' + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const name = ${JSON.stringify(authUser)};
    const password = ${JSON.stringify(authPassword)};
    // Регистрация может быть отвергнута, если пользователь этого
    // прогона уже есть: тогда просто входим.
    await post('/auth/register/', {
      username: name,
      email: name + '@example.com',
      password,
      consent_pdn: true,
    });
    const res = await post('/auth/login/', { login: name, password });
    if (!res.ok) return { ok: false, status: res.status };
    const body = await res.json();
    localStorage.setItem('aurabuilder.access', body.access);
    localStorage.setItem('aurabuilder.refresh', body.refresh);
    return { ok: true };
  `);

await page.send('Page.reload', { ignoreCache: true });
await new Promise((r) => setTimeout(r, 6000));

// Список проектов — точка входа после входа. Редактор открывается
// только явным выбором, поэтому до пробы холста нужно нажать на первую
// карточку: пустой список означает, что редактор вообще не отрисуется.
const dashReady = await waitFor(page, '.dash__grid, .dash__empty', 20000);
if (!dashReady) throw new Error('после входа не открылся список проектов');

if (await has(page, '.dash__empty')) {
  await click(page, '.dash__empty .btn--primary');
  await fill(page, '.dash__input', 'Проект автопроверки');
  await click(page, '.dash__create .btn--primary');
} else {
  await click(page, '.dash__card .dash__open');
}
// Ждём не контейнер, а сам canvas Konva: модуль с холстом грузится
// лениво, и контейнер появляется на несколько сотен миллисекунд раньше.
if (!(await waitFor(page, '.canvas canvas', 25000))) {
  throw new Error('редактор не открылся после выбора проекта');
}
await new Promise((r) => setTimeout(r, 1500));

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
  /*
   * Отметка шага включается переменной PROBE_TRACE и нужна только при
   * разборе зависания: по последней напечатанной метке видно, на
   * каком действии браузер перестал отвечать. В обычном прогоне вывод
   * остаётся чистым.
   */
  let step = 0;
  const mark = (label) => {
    step += 1;
    if (process.env['PROBE_TRACE']) console.log(`шаг ${step}: ${label}`);
  };

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

  /* ------------------------------------------------------------------ */
  /*  Вход и права                                                      */
  /* ------------------------------------------------------------------ */

  /*
   * Вход через интерфейс.
   *
   * Проверяются две ветки: повторная регистрация (сервер должен
   * отказать, иначе можно было бы занять чужой логин) и вход по
   * уже существующему пользователю. Новый пользователь здесь не
   * создаётся намеренно: каждый прогон оставлял бы запись в базе, а
   * проверять нужно поведение формы, а не её регистрацию — её уже
   * проверил вход через API в начале.
   */
  await page.send('Runtime.evaluate', {
    expression: `localStorage.clear()`,
  });
  await reload(page);
  await waitFor(page, '.auth__card', 15000);

  results.push(['без входа показан экран входа', await has(page, '.auth__card')]);

// Каталог модулей не требует входа: он не содержит пользовательских
  // данных, и палитра нужна редактору раньше токена.
  const anonCatalog = await fetchFromPage(page, '/modules/?stage=3', false);
  results.push(['каталог модулей доступен без входа', anonCatalog.status === 200]);

  // Регистрация уже существующего логина должна быть отвергнута.
  await click(page, '.auth__tab:nth-child(2)');
  await fill(page, 'input[name="username"]', authUser);
  await fill(page, 'input[name="email"]', `${authUser}@example.com`);
  await fill(page, 'input[name="password"]', authPassword);
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      const box = document.querySelector('.auth__consent input');
      if (box && !box.checked) box.click();
    })()`,
  });
  await click(page, '.auth__submit');
  await new Promise((r) => setTimeout(r, 900));

  const duplicateError = await text(page, '.auth__error');
  results.push([
    'занятый логин не проходит регистрацию',
    duplicateError.includes('занят'),
  ]);

  // Регистрация без согласия на обработку ПДн невозможна (152-ФЗ).
  // Логин здесь другой: занятое имя отвергается раньше, чем проверяется
  // согласие, и до сути проверки дело не дошло бы.
  await fill(page, 'input[name="username"]', `${authUser}-noconsent`);
  await fill(page, 'input[name="email"]', `${authUser}-noconsent@example.com`);
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      const box = document.querySelector('.auth__consent input');
      if (box && box.checked) box.click();
    })()`,
  });
  await click(page, '.auth__submit');
  await new Promise((r) => setTimeout(r, 700));
  results.push([
    'регистрация без согласия на ПДн не проходит',
    (await text(page, '.auth__error')).includes('персональных'),
  ]);

  // Вход по существующему пользователю.
  await click(page, '.auth__tab:nth-child(1)');
  await fill(page, 'input[name="login"]', authUser);
  await fill(page, 'input[name="password"]', authPassword);
  await click(page, '.auth__submit');
  await waitFor(page, '.editor', 20000);

  // После входа открывается список проектов: редактор запускается
  // только явным выбором проекта (Dashboard V1).
  results.push([
    'вход через форму открыл список проектов',
    await has(page, '.dash__toolbar'),
  ]);

  const stored = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => ({
      access: !!localStorage.getItem('aurabuilder.access'),
      refresh: !!localStorage.getItem('aurabuilder.refresh'),
    }))()`,
  });
  results.push(['токены сохранены локально', stored.result.value.access === true]);

  await reload(page);
  await waitFor(page, '.dash__toolbar', 20000);
  results.push([
    'после перезагрузки сессия жива',
    await has(page, '.dash__toolbar'),
  ]);

  // Список проектов не должен содержать чужие: у нового пользователя
  // появляется проект только от openProject.
  const projects = await fetchFromPage(page, '/projects/', true);
  const projectCount = projects.count;
  results.push([
    `свои проекты видны (${typeof projectCount === 'number' ? projectCount : 'нет данных'})`,
    projects.status === 200 && projectCount >= 1,
  ]);

  // Без токена сервер должен отказать.
  const anon = await fetchFromPage(page, '/projects/', false);
  results.push(['без токена список проектов закрыт', anon.status === 401]);

  // Выход возвращает на экран входа и убирает токены.
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      const btn = [...document.querySelectorAll('button')]
        .find(b => b.textContent.trim() === 'Выйти');
      if (btn) btn.click();
    })()`,
  });
  await waitFor(page, '.auth__card', 15000);
  results.push(['выход возвращает на экран входа', await has(page, '.auth__card')]);

  /*
   * Выход запрос на сервере асинхронный, поэтому токены исчезают не
   * сразу после щелчка: экран входа появляется раньше, чем localStorage
   * очищается. Опрос даёт несколько секунд — иначе проверка ловила
   * гонку, а не ошибку.
   */
  let clearedValue = { access: 'нет данных', refresh: 'нет данных' };
  for (let attempt = 0; attempt < 10; attempt++) {
    const probe = await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `(() => ({
        access: localStorage.getItem('aurabuilder.access'),
        refresh: localStorage.getItem('aurabuilder.refresh'),
      }))()`,
    });
    clearedValue = probe.result.value ?? {};
    if (clearedValue.access === null && clearedValue.refresh === null) break;
    await new Promise((r) => setTimeout(r, 400));
  }
  results.push([
    `после выхода токены убраны (${JSON.stringify(clearedValue)})`,
    clearedValue.access === null && clearedValue.refresh === null,
  ]);


  /* ------------------------------------------------------------------ */
  /*  Список проектов                                                    */
  /* ------------------------------------------------------------------ */

  /*
   * Список проверяется после входа и до редактора: он теперь точка
   * входа, и ошибка в нём выглядела бы как «холст не грузится».
   *
   * Создаётся проект с именем из времени прогона: проверка удаления
   * обязана быть разрушающей, а на постоянном имени прогон удалил бы
   * проект, который следующий тест использует.
   */
  const dashName = `Автопроверка ${Date.now().toString(36)}`;

  // Предыдущий блок закончился выходом, поэтому токенов нет и
  // приложение показывает экран входа. Входим заново тем же
  // пользователем: сценарии списка должны идти после успешного входа.
  const again = await evalAsync(page, `
    const res = await fetch('/api/auth/login/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        login: ${JSON.stringify(authUser)},
        password: ${JSON.stringify(authPassword)},
      }),
    });
    if (!res.ok) return { ok: false, status: res.status };
    const body = await res.json();
    localStorage.setItem('aurabuilder.access', body.access);
    localStorage.setItem('aurabuilder.refresh', body.refresh);
    return { ok: true };
  `);
  if (!again?.ok) {
    throw new Error('повторный вход не удался: ' + JSON.stringify(again));
  }

  // Список получается перезагрузкой, а не кнопкой возврата: экран
  // приложения не хранится в URL, поэтому после reload открывается
  // именно список — это проверяется надёжнее, чем клик по кнопке.
  mark('возврат к списку проектов');
  await reload(page);
  if (!(await waitFor(page, '.dash__toolbar', 15000))) {
    throw new Error('список проектов не открылся после перезагрузки');
  }

  mark('открытие формы создания');
  await click(page, '.dash__toolbar .btn--primary');
  await fill(page, '.dash__input', dashName);
  await click(page, '.dash__create .btn--primary');
  await new Promise((r) => setTimeout(r, 1200));

  // Форма могла не отправиться: кнопка «Создать» остаётся выключенной,
  // если поле пустое. Проверяем до перехода дальше, иначе следующая
  // ошибка указывала бы совсем не на то место.
  const afterCreate = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `JSON.stringify({
      input: document.querySelector('.dash__input')?.value ?? null,
      disabled: document.querySelector('.dash__create .btn--primary')?.disabled ?? null,
      inEditor: !!document.querySelector('.canvas'),
      error: document.querySelector('.dash__error')?.textContent ?? null,
    })`,
  });
  results.push([
    `создание проекта отправило форму (${afterCreate.result.value})`,
    afterCreate.result.value.includes('"inEditor":true'),
  ]);

  results.push([
    'создание проекта открыло редактор',
    await has(page, '.canvas'),
  ]);

  mark('возврат из редактора по кнопке');
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      const btn = [...document.querySelectorAll('button')]
        .find(b => b.getAttribute('aria-label') === 'К списку проектов');
      if (btn) btn.click();
    })()`,
  });
  await waitFor(page, '.dash__grid', 15000);

  const cardExists = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const cards = [...document.querySelectorAll('.dash__card-name')];
      return cards.map(c => c.textContent);
    })()`,
  });
  const names = cardExists.result.value ?? [];
  results.push([
    'новый проект появился в списке',
    names.includes(dashName),
  ]);

  mark('проверка списка после создания');
  // Переименование: поле в карточке, без системного диалога.
  const newName = `${dashName} (переименован)`;
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      const card = [...document.querySelectorAll('.dash__card')]
        .find(c => c.querySelector('.dash__card-name')?.textContent === ${JSON.stringify(dashName)});
      const btn = card && [...card.querySelectorAll('button')]
        .find(b => b.title === 'Переименовать');
      if (btn) btn.click();
    })()`,
  });
  await waitFor(page, '.dash__rename-input', 10000);
  await fill(page, '.dash__rename-input', newName);
  await click(page, '.dash__rename .btn--primary');
  await new Promise((r) => setTimeout(r, 900));

  const namesAfterRename = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `[...document.querySelectorAll('.dash__card-name')].map(c => c.textContent)`,
  });
  results.push([
    'переименование сохранилось на сервере',
    (namesAfterRename.result.value ?? []).includes(newName),
  ]);

  // Удаление: диалог подтверждения.
  await page.send('Runtime.evaluate', {
    expression: `(() => {
      const card = [...document.querySelectorAll('.dash__card')]
        .find(c => c.querySelector('.dash__card-name')?.textContent === ${JSON.stringify(newName)});
      const btn = card && [...card.querySelectorAll('button')]
        .find(b => b.title === 'Удалить');
      if (btn) btn.click();
    })()`,
  });
  await waitFor(page, '.modal__card', 10000);
  const modalTitle = await text(page, '.modal__title');
  results.push(['удаление спрашивает подтверждение', modalTitle.includes('Удалить')]);

  if (!(await has(page, '.modal__actions .btn--primary'))) {
    // Диалог не появился: показываем, что на экране, иначе ошибка
    // указывала бы только на селектор кнопки.
    const state = await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `JSON.stringify({
        hasModal: !!document.querySelector('.modal'),
        cards: [...document.querySelectorAll('.dash__card-name')].map(c => c.textContent),
      })`,
    });
    throw new Error('диалог удаления не открылся; состояние: ' + state.result.value);
  }
  mark('подтверждение удаления');
  await click(page, '.modal__actions .btn--primary');
  await new Promise((r) => setTimeout(r, 900));

  const afterDelete = await page.send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const cards = [...document.querySelectorAll('.dash__card-name')];
      return cards.map(c => c.textContent);
    })()`,
  });
  results.push([
    'удалённый проект исчез из списка',
    !(afterDelete.result.value ?? []).includes(newName),
  ]);

  mark('проверка пустого состояния');
  // Пустое состояние объясняет следующий шаг и содержит кнопку.
  // Проверяется только когда список действительно пуст: у пользователя
  // к этому моменту есть созданный ранее проект, и требовать пустоты
  // означало бы запретить собственные проекты.
  const isEmpty = await has(page, '.dash__empty');
  if (isEmpty) {
    const emptyState = await page.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `(() => {
        const empty = document.querySelector('.dash__empty');
        return {
          has: !!empty,
          hasButton: !!empty?.querySelector('.btn--primary'),
        };
      })()`,
    });
    results.push([
      'пустое состояние объясняет следующий шаг',
      emptyState.result.value.has === true && emptyState.result.value.hasButton === true,
    ]);
  } else {
    results.push(['список не пуст — пустое состояние не показывается', true]);
  }

  // Возвращаемся в редактор: сценарии холста идут дальше. Кнопка
  // «Новый проект» есть в обоих состояниях списка, а форма создания
  // открывается в панели инструментов.
  await click(page, '.dash__toolbar .btn--primary');
  await fill(page, '.dash__input', dashName);
  await click(page, '.dash__create .btn--primary');
  if (!(await waitFor(page, '.canvas canvas', 25000))) {
    throw new Error('редактор не открылся после создания проекта');
  }

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
