/**
 * Ручная проверка шести статических коммерческих модулей на холсте.
 *
 * Зачем отдельный скрипт: палитра редактора показывает модули текущего
 * этапа выпуска (CURRENT_STAGE = 3, ТЗ п.12), поэтому модули этапа 6
 * через неё не добавить. Проект с ними создаётся через API, а проверка
 * идёт по отрисовке холста — так же, как её делает screenshot-editor.
 *
 * Запуск:
 *   node tools/probe-commerce.mjs http://127.0.0.1:8080/ \
 *     --login owner --password '...'
 */

import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

const MODULES = [
  {
    module: 'promo.banner',
    label: 'Промо-баннер',
    props: {
      heading: 'Лето со скидками',
      text: 'Скидка 20% до конца месяца',
      buttonLabel: 'Смотреть каталог',
      buttonLink: '/catalog',
      background: 'accent',
    },
  },
  {
    module: 'promo.pricing',
    label: 'Тарифы',
    props: { titleField: 'plan', priceField: 'cost', periodField: 'term' },
  },
  {
    module: 'shop.compare',
    label: 'Сравнение',
    props: { titleField: 'name', fields: 'cost\nweight', priceField: 'cost', limit: 4 },
  },
  {
    module: 'shop.reviews',
    label: 'Отзывы',
    props: { authorField: 'who', textField: 'text', ratingField: 'stars', limit: 6 },
  },
  {
    module: 'shop.stock',
    label: 'Остатки',
    props: { field: 'qty', label: 'Штук', lowThreshold: 5 },
  },
  {
    module: 'shop.order',
    label: 'Заявка',
    props: { heading: 'Заявка на расчёт', fields: 'Имя\nТелефон\nКомментарий' },
  },
];

const url = process.argv[2] ?? 'http://127.0.0.1:8080/';
const login = argValue('--login');
const password = argValue('--password');

function argValue(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : process.env.PROBE_PASSWORD;
}

/**
 * Дерево страницы для проверки.
 *
 * Страница на холсте 720×900, поэтому шесть блоков в столбик не
 * поместились бы: два нижних оказались бы за нижним краем и в снимок
 * не попали. Две колонки по три блока умещаются целиком.
 */
function tree() {
  const colWidth = 220;
  return {
    width: 720,
    blocks: MODULES.map((item, i) => ({
      id: `commerce-${i + 1}`,
      module: item.module,
      x: 20 + (i % 3) * 235,
      y: 20 + Math.floor(i / 3) * 300,
      width: colWidth,
      height: 280,
      label: item.label,
      props: item.props,
    })),
  };
}

async function call(path, options = {}) {
  const response = await fetch(new URL(`api/${path}`, url), options);
  const text = await response.text();
  if (!response.ok) throw new Error(`${path}: ${response.status} ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : null;
}

const session = await call('auth/login/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ login, password }),
});
const auth = { Authorization: `Bearer ${session.access}`, 'Content-Type': 'application/json' };

const project = await call('projects/', {
  method: 'POST',
  headers: auth,
  body: JSON.stringify({ name: `Коммерческие модули ${Date.now()}`, tree: tree() }),
});
console.log(`создан проект ${project.id}`);

// Источник нужен блокам, которые читают записи: без него холст покажет
// пустые заглушки, и проверить было бы нечего.
const source = await call(`projects/${project.id}/data/`, {
  method: 'POST',
  headers: auth,
  body: JSON.stringify({
    name: 'Каталог',
    fields: [
      { key: 'name', label: 'Название', type: 'text', required: true },
      { key: 'plan', label: 'Тариф', type: 'text', required: false },
      { key: 'cost', label: 'Цена', type: 'number', required: false },
      { key: 'weight', label: 'Вес', type: 'number', required: false },
      { key: 'who', label: 'Автор', type: 'text', required: false },
      { key: 'text', label: 'Отзыв', type: 'text', required: false },
      { key: 'stars', label: 'Оценка', type: 'number', required: false },
      { key: 'qty', label: 'Остаток', type: 'number', required: false },
    ],
  }),
});

const rows = [
  { name: 'Роза', plan: 'Старт', cost: 0, weight: 0.4, who: 'Ирина', text: 'Пришло быстро', stars: 5, qty: 3 },
  { name: 'Тюльпан', plan: 'Бизнес', cost: 2500, weight: 0.3, who: 'Павел', text: 'Цветок завял', stars: 2, qty: 4 },
];
for (const row of rows) {
  await call(`data/${source.id}/records/`, {
    method: 'POST',
    headers: auth,
    body: JSON.stringify({ data: row }),
  });
}

// Привязываем источник к блокам, которые его читают.
const linked = tree();
for (const block of linked.blocks) {
  if (block.module !== 'promo.banner' && block.module !== 'shop.order') {
    block.props.source = source.id;
  }
}
await call(`projects/${project.id}/`, {
  method: 'PUT',
  headers: auth,
  body: JSON.stringify({
    name: project.name,
    tree: linked,
    expectedVersion: project.version,
  }),
});

console.log(`источник ${source.id} с ${rows.length} записями`);

// Холст проверяется браузером: без него модуль не рисуется вовсе.
// Один снимок достаточен: все шесть блоков помещаются на страницу.
const probe = spawn(
  process.execPath,
  [
    'tools/probe.mjs',
    url,
    '--login',
    login,
    '--password',
    password,
    '--open-project',
    '--wait',
    '.canvas canvas',
    '--eval',
    `(() => {
      const holder = document.querySelector('.canvas');
      return {
        blocks: Number(holder?.dataset.blocks ?? -1),
        canvas: !!document.querySelector('.canvas canvas'),
      };
    })()`,
    '--shot',
    join(root, 'commerce-modules.png'),
  ],
  { cwd: root, stdio: 'inherit' },
);

const code = await new Promise((done) => probe.on('close', done));
if (code !== 0) process.exitCode = code;

console.log('\nснимок: commerce-modules.png');