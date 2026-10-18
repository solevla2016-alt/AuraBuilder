/**
 * Демонстрационный проект на локальном стенде.
 *
 * Зачем он: собранный сайт удобнее смотреть глазами, чем читать
 * build-manifest. Скрипт создаёт проект, кладёт в него осмысленные
 * блоки (текст, карточки, галерея с загруженными картинками,
 * изображение, данные из источника), фиксирует версию и
 * публикует. Адрес печатается в конце — его можно открыть в браузере.
 *
 * Запуск:
 *   node tools/demo-stand.mjs http://127.0.0.1:8080/
 */

const BASE = process.argv[2] ?? 'http://127.0.0.1:8080/';
const API = `${BASE.replace(/\/$/, '')}/api`;
const LOGIN = process.env['DEMO_LOGIN'] ?? 'demo-owner';
const PASSWORD = process.env['DEMO_PASSWORD'] ?? 'Verysecret123';

import zlib from 'node:zlib';

// Картинки рисуются прямо здесь: генерировать их файлами на диске
// незачем, а конструктор всё равно проверяет сигнатуру, а не имя.
function png(width, height, [r, g, b]) {
  const raw = [];
  for (let y = 0; y < height; y += 1) {
    const row = new Uint8Array(1 + width * 3);
    for (let x = 0; x < width; x += 1) {
      // Лёгкая градиентная заливка: однотонная картинка на сайте
      // выглядит как заглушка, а градиент сразу показывает, что это
      // настоящий файл.
      const k = (x / width) * 0.45 + (y / height) * 0.35;
      row[1 + x * 3] = Math.round(r + (255 - r) * k);
      row[2 + x * 3] = Math.round(g + (255 - g) * k);
      row[3 + x * 3] = Math.round(b + (255 - b) * k);
    }
    raw.push(row);
  }
  const chunks = [Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])];
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  chunks.push(chunk('IHDR', ihdr));
  chunks.push(chunk('IDAT', idat(raw)));
  chunks.push(chunk('IEND', Buffer.alloc(0)));
  return Buffer.concat(chunks);
}

/** DEFLATE для IDAT. Сжатие берётся из встроенного zlib Node:
 *  собранный вручную поток без блоков DEFLATE проходил проверку по
 *  сигнатуре, но браузер такую картинку не декодировал — файл молча
 *  не отображался на собранном сайте.
 */
function idat(rows) {
  return zlib.deflateSync(Buffer.concat(rows));
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body) >>> 0);
  return Buffer.concat([length, body, crc]);
}

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = -1;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return c ^ -1;
}

async function call(path, { method = 'GET', body, token, raw } = {}) {
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (body !== undefined && !raw) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: raw ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let parsed = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = text;
  }
  if (!res.ok) {
    const detail =
      parsed && typeof parsed === 'object'
        ? parsed.detail ?? JSON.stringify(parsed)
        : String(parsed).slice(0, 200);
    throw new Error(`${method} ${path} -> HTTP ${res.status}: ${detail}`);
  }
  return parsed;
}

/** Адрес медиатеки для уже загруженного файла. */
async function upload(projectId, name, buffer, token) {
  const form = new FormData();
  form.append('file', new File([buffer], name, { type: 'image/png' }));
  return call(`/projects/${projectId}/assets/`, { method: 'POST', body: form, token, raw: true });
}

function block(id, module, x, y, width, height, label, props = {}) {
  return { id, module, x, y, width, height, label, props };
}

async function main() {
  const tokens = await call('/auth/login/', {
    method: 'POST',
    body: { login: LOGIN, password: PASSWORD },
  }).catch(async () => {
    const reg = await call('/auth/register/', {
      method: 'POST',
      body: {
        username: LOGIN,
        email: `${LOGIN}@example.com`,
        password: PASSWORD,
        consent_pdn: true,
      },
    });
    return call('/auth/login/', {
      method: 'POST',
      body: { login: LOGIN, password: PASSWORD },
    });
  });
  const token = tokens.access;
  console.log(`вошли как ${LOGIN}`);

  // Тариф Start: демо создаёт больше одного проекта.
  await call('/billing/subscription/change/', {
    method: 'POST',
    body: { plan: 'start' },
    token,
  }).catch(() => {});

  const slug = `demo-${Math.random().toString(36).slice(2, 8)}`;
  // Тариф поднимается до Business, а не до Start: демо запускают
  // повторно, и на Start пятый запуск упирается в лимит проектов и
  // падает с 402 вместо показа сайта.
  await call('/billing/subscription/change/', {
    method: 'POST',
    body: { plan: 'business' },
    token,
  }).catch(() => {});
  const project = await call('/projects/', {
    method: 'POST',
    body: { name: 'Мастерская «Керамика»', slug },
    token,
  });
  const pid = project.id;
  console.log(`проект создан: ${pid}`);

  const hero = png(1200, 700, [198, 140, 96]);
  const bowl = png(900, 700, [122, 158, 160]);
  const cup = png(900, 700, [186, 122, 140]);
  const plate = png(900, 700, [140, 152, 176]);
  const uploaded = [];
  for (const [name, buf] of [
    ['мастерская.png', hero],
    ['миска.png', bowl],
    ['кружка.png', cup],
    ['тарелка.png', plate],
  ]) {
    uploaded.push(await upload(pid, name, buf, token));
  }
  console.log(`картинок загружено: ${uploaded.length}`);

  const source = await call(`/projects/${pid}/data/`, {
    method: 'POST',
    body: {
      name: 'Изделия',
      key: 'izdeliya',
      description: 'Что делаем в мастерской',
      fields: [
        { key: 'name', label: 'Название', type: 'text', required: true },
        { key: 'material', label: 'Материал', type: 'text', required: false },
        { key: 'price', label: 'Цена', type: 'number', required: false },
      ],
    },
    token,
  });
  // Поле price объявлено числом, поэтому и значение числа: сервер
// проверяет тип по объявленной схеме и отвергает строку с рублём.
const rows = [
  { name: 'Миска «Волна»', material: 'Камень, глазурь', price: 4800 },
  { name: 'Кружка «Утро»', material: 'Камень, белый ангоб', price: 3200 },
  { name: 'Тарелка «Поле»', material: 'Красная глина', price: 3900 },
];
  for (const row of rows) {
    // Записи адресуются под /api/data/, а не под проектом: у источника
    // свой адрес, чтобы один и тот же список не пришлось искать заново
    // по идентификатору проекта (apps/data_sources/urls.py).
    await call(`/data/${source.id}/records/`, {
      method: 'POST',
      body: { data: row },
      token,
    });
  }
  console.log(`записей в источнике: ${rows.length}`);

  const gallery = uploaded.slice(1).map((a) => a.url).join(',');
  // Ширина страницы и раскладка задаются в самом дереве: без неё
  // сервер отвергает дерево («tree.width: ожидается число»).
  const tree = {
    version: 1,
    width: 1200,
    settings: {},
    // Имена свойств и допустимые значения берутся из реестра
    // (packages/registry/props.json): сервер проверяет дерево по схеме
    // модуля и отвергает неизвестное значение, а не молча выкидывает.
    blocks: [
      block('b1', 'section.hero', 40, 40, 1120, 320, 'Первый экран', {
        heading: 'Мастерская керамики',
        subheading: 'Гончарный круг, каменная глина и обжиг в печи, которую сложили сами.',
        buttonLabel: 'Смотреть изделия',
        buttonLink: '#',
        background: 'accent',
        align: 'left',
        size: 'regular',
      }),
      block('b2', 'media.image', 40, 390, 1120, 420, 'Мастерская', {
        src: uploaded[0].url,
        alt: 'Гончарный круг в мастерской',
      }),
      block('b3', 'text.heading', 40, 840, 1120, 70, 'Заголовок изделий', {
        text: 'Что мы делаем',
        level: 'h2',
        align: 'left',
      }),
      block('b4', 'data.collection', 40, 920, 1120, 420, 'Каталог изделий', {
        source: String(source.id),
        limit: 10,
      }),
      block('b5', 'section.gallery', 40, 1370, 1120, 520, 'Галерея работ', {
        heading: 'Галерея',
        images: gallery,
        columns: 3,
        gap: 16,
      }),
      block('b6', 'section.cta', 40, 1920, 1120, 200, 'Призыв записаться', {
        heading: 'Запишитесь на обжив',
        buttonLabel: 'Записаться',
      }),
    ],
  };

  // Дерево сначала сохраняется в проект, и только потом снимается
  // версия: POST /versions/ снимает текущее дерево проекта и переданное
  // в теле игнорирует (apps/projects/views.py, version_list).
  await call(`/projects/${pid}/`, {
    method: 'PATCH',
    body: { tree },
    token,
  });

  const version = await call(`/projects/${pid}/versions/`, {
    method: 'POST',
    body: { label: 'Демо-версия' },
    token,
  });
  console.log(`версия зафиксирована: ${version.number}`);

  // Публикация живёт под /site/, а не под /publish/ (apps/publications/urls.py).
const published = await call(`/projects/${pid}/site/`, {
    method: 'POST',
    body: {},
    token,
  });
  const siteUrl = published.url ?? `${BASE}sites/${published.site?.slug ?? slug}/`;
  console.log('');
  console.log('сайт опубликован:');
  console.log(siteUrl);
  console.log('');
  console.log(`архив: ${BASE.replace(/\/$/, '')}/api/projects/${pid}/export/`);
  return siteUrl;
}

main().catch((e) => {
  console.error('не получилось:', e.message);
  process.exitCode = 1;
});