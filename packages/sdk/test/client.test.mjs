/**
 * Клиент против настоящего HTTP-сервера: проверяется контракт запросов
 * и разбор ответов, а не моки fetch. Подмена fetch проверяется отдельно —
 * только для случая, когда сети нет вовсе.
 */

import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { after, before, beforeEach, test } from 'node:test';

import { AuraApiError, AuraClient } from '../dist/index.js';

const state = { calls: [], refreshes: 0, refreshOnce: false };

const project = {
  id: 'p1',
  name: 'Сайт',
  version: 7,
  role: 'owner',
  blockCount: 3,
  pageCount: 1,
  createdAt: '2026-01-01T00:00:00+00:00',
  updatedAt: null,
};

const page = {
  id: null,
  slug: '',
  title: 'Сайт',
  seoTitle: '',
  seoDescription: '',
  blockCount: 3,
  version: 7,
  updatedAt: null,
  isHome: true,
};

function sendJson(response, status, data) {
  const body = JSON.stringify(data);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  response.end(body);
}

function envelope(response, status, code, message, extra = {}) {
  sendJson(response, status, { error: { code, message, ...extra } });
}

function readBody(request) {
  return new Promise((resolve) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
  });
}

let server;
let baseUrl;

before(async () => {
  server = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1');
    state.calls.push({
      method: request.method,
      path: url.pathname,
      search: url.search,
      authorization: request.headers.authorization ?? null,
    });

    if (url.pathname === '/api/auth/login/') {
      const body = JSON.parse(await readBody(request));
      if (body.login !== 'owner' || body.password !== 'secret') {
        sendJson(response, 400, {
          non_field_errors: ['Неверный логин или пароль.'],
        });
        return;
      }
      sendJson(response, 200, {
        access: 'good',
        refresh: 'refresh-good',
        user: {
          id: 1,
          username: 'owner',
          email: 'owner@example.com',
          first_name: '',
          last_name: '',
        },
      });
      return;
    }

    if (url.pathname === '/api/auth/refresh/') {
      state.refreshes += 1;
      const body = JSON.parse(await readBody(request));
      // Ротация: повторный refresh со старым токеном уже не проходит.
      if (state.refreshOnce && state.refreshes > 1) {
        sendJson(response, 401, { detail: 'Токен уже использован.' });
        return;
      }
      if (body.refresh !== 'refresh-good') {
        sendJson(response, 401, {
          detail: 'Токен недействителен.',
          code: 'token_not_valid',
        });
        return;
      }
      sendJson(response, 200, { access: 'good' });
      return;
    }

    if (url.pathname === '/api/auth/logout/') {
      response.writeHead(204);
      response.end();
      return;
    }

    if (
      url.pathname.startsWith('/api/v1/') &&
      request.headers.authorization !== 'Bearer good'
    ) {
      envelope(response, 401, 'unauthorized', 'Токен истёк.');
      return;
    }

    if (url.pathname === '/api/v1/') {
      sendJson(response, 200, {
        apiVersion: 1,
        service: 'AuraBuilder',
        auth: {
          type: 'bearer',
          obtain: '/api/auth/login/',
          refresh: '/api/auth/refresh/',
        },
        endpoints: [{ method: 'GET', path: '/api/v1/projects/' }],
        pagination: {
          limit: { default: 20, max: 50 },
          offset: { default: 0 },
        },
        mcp: {
          endpoint: '/api/v1/mcp/',
          transport: 'streamable-http',
          sse: false,
        },
      });
      return;
    }

    if (url.pathname === '/api/v1/projects/') {
      sendJson(response, 200, {
        data: [project],
        meta: { total: 1, limit: 2, offset: 3 },
      });
      return;
    }

    if (url.pathname === '/api/v1/projects/p1/') {
      sendJson(response, 200, {
        ...project,
        brand: {
          accent: '#112233',
          font: 'sans',
          signature: '',
          utmSource: '',
          utmMedium: '',
          utmCampaign: '',
        },
        tree: { blocks: [{ type: 'hero' }] },
        pages: [page],
      });
      return;
    }

    if (url.pathname === '/api/v1/projects/p1/pages/') {
      sendJson(response, 200, { projectId: 'p1', pages: [page] });
      return;
    }

    if (url.pathname === '/api/v1/projects/p1/pages/home/') {
      sendJson(response, 200, { ...page, tree: { blocks: [] } });
      return;
    }

    if (url.pathname === '/api/v1/projects/p1/versions/') {
      sendJson(response, 200, {
        projectId: 'p1',
        versions: [
          {
            number: 7,
            label: 'Перед запуском',
            createdAt: '2026-02-01T10:00:00+00:00',
            blockCount: 3,
            pageCount: 1,
          },
        ],
      });
      return;
    }

    if (url.pathname === '/api/v1/projects/p1/export/') {
      const bytes = Buffer.from([0x50, 0x4b, 0x03, 0x04]);
      response.writeHead(200, {
        'Content-Type': 'application/zip',
        'Content-Disposition': 'attachment; filename="site-static.zip"',
        'X-AuraBuilder-Version': '7',
        'X-AuraBuilder-Warnings': '2',
        'X-AuraBuilder-PWA': '1',
        'Content-Length': bytes.length,
      });
      response.end(bytes);
      return;
    }

    if (url.pathname === '/api/v1/projects/missing/') {
      envelope(response, 404, 'not_found', 'Проект не найден.');
      return;
    }

    envelope(response, 404, 'not_found', 'Нет такого маршрута.');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
});

beforeEach(() => {
  state.calls = [];
  state.refreshes = 0;
  state.refreshOnce = false;
});

test('вход сохраняет токены, следующий запрос идёт с Bearer', async () => {
  const client = new AuraClient({ baseUrl });
  const result = await client.login('owner', 'secret');

  assert.equal(result.user.username, 'owner');
  assert.equal(client.accessToken, 'good');

  const listing = await client.projects();
  assert.equal(listing.data[0].name, 'Сайт');
  assert.equal(listing.meta.total, 1);

  const last = state.calls[state.calls.length - 1];
  assert.equal(last.authorization, 'Bearer good');
});

test('projects передаёт limit и offset в запрос', async () => {
  const client = new AuraClient({ baseUrl, token: 'good' });
  const listing = await client.projects({ limit: 2, offset: 3 });

  assert.deepEqual(listing.meta, { total: 1, limit: 2, offset: 3 });
  assert.equal(state.calls[0].search, '?limit=2&offset=3');
});

test('описание, проект, страницы и версии разбираются по контракту', async () => {
  const client = new AuraClient({ baseUrl, token: 'good' });

  const description = await client.describe();
  assert.equal(description.apiVersion, 1);
  assert.equal(description.auth.type, 'bearer');

  const detail = await client.project('p1');
  assert.equal(detail.brand.accent, '#112233');
  assert.equal(detail.pages.length, 1);
  assert.deepEqual(detail.tree, { blocks: [{ type: 'hero' }] });

  const listing = await client.pages('p1');
  assert.equal(listing.pages[0].isHome, true);

  const home = await client.page('p1', 'home');
  assert.deepEqual(home.tree, { blocks: [] });

  const versions = await client.versions('p1');
  assert.equal(versions.versions[0].label, 'Перед запуском');
});

test('пустой slug не ходит в сеть: это главная, её дерево в project()', () => {
  const client = new AuraClient({ baseUrl, token: 'good' });
  assert.throws(() => client.page('p1', ''), /project\(\)/);
  assert.equal(state.calls.length, 0);
});

test('ошибка v1 приходит с кодом, статусом и подробностями', async () => {
  const client = new AuraClient({ baseUrl, token: 'good' });

  await assert.rejects(
    client.project('missing'),
    (error) => {
      assert.ok(error instanceof AuraApiError);
      assert.ok(error instanceof Error);
      assert.equal(error.name, 'AuraApiError');
      assert.equal(error.status, 404);
      assert.equal(error.code, 'not_found');
      assert.equal(error.message, 'Проект не найден.');
      return true;
    },
  );
});

test('ошибка входа DRF превращается в понятное сообщение', async () => {
  const client = new AuraClient({ baseUrl });

  await assert.rejects(
    client.login('owner', 'wrong'),
    (error) => {
      assert.equal(error.code, 'invalid_request');
      assert.equal(error.status, 400);
      assert.equal(error.message, 'Неверный логин или пароль.');
      return true;
    },
  );
});

test('на 401 клиент обновляет токен и повторяет запрос один раз', async () => {
  const client = new AuraClient({
    baseUrl,
    token: 'expired',
    refreshToken: 'refresh-good',
  });

  const listing = await client.projects();
  assert.equal(listing.data.length, 1);
  assert.equal(state.refreshes, 1);
  assert.equal(client.accessToken, 'good');
  assert.deepEqual(
    state.calls.map((call) => `${call.method} ${call.path}`),
    [
      'GET /api/v1/projects/',
      'POST /api/auth/refresh/',
      'GET /api/v1/projects/',
    ],
  );
});

test('параллельные 401 ждут один refresh, а не ломают ротацию', async () => {
  state.refreshOnce = true;
  const client = new AuraClient({
    baseUrl,
    token: 'expired',
    refreshToken: 'refresh-good',
  });

  const [first, second] = await Promise.all([
    client.projects(),
    client.projects(),
  ]);
  assert.equal(first.data.length, 1);
  assert.equal(second.data.length, 1);
  assert.equal(state.refreshes, 1);
  assert.equal(client.accessToken, 'good');
});

test('без refresh-токена 401 возвращается вызывающему', async () => {
  const client = new AuraClient({ baseUrl, token: 'expired' });

  await assert.rejects(
    client.projects(),
    (error) => error.code === 'unauthorized' && error.status === 401,
  );
  assert.equal(state.refreshes, 0);
});

test('refresh без токена не делает запрос', async () => {
  const client = new AuraClient({ baseUrl, token: 'good' });

  await assert.rejects(
    client.refresh(),
    (error) => error.code === 'unauthorized' && error.status === 401,
  );
  assert.equal(state.calls.length, 0);
});

test('экспорт отдаёт байты и сведения из заголовков', async () => {
  const client = new AuraClient({ baseUrl, token: 'good' });
  const archive = await client.exportArchive('p1', {
    version: 7,
    pwa: true,
    baseUrl: 'https://site.example',
  });

  assert.deepEqual([...archive.bytes], [0x50, 0x4b, 0x03, 0x04]);
  assert.equal(archive.filename, 'site-static.zip');
  assert.equal(archive.contentType, 'application/zip');
  assert.equal(archive.version, 7);
  assert.equal(archive.warnings, 2);
  assert.equal(archive.pwa, true);
  assert.equal(
    state.calls[0].search,
    '?version=7&pwa=1&baseUrl=https%3A%2F%2Fsite.example',
  );
});

test('выход отзывает refresh и забывает токены', async () => {
  const client = new AuraClient({
    baseUrl,
    token: 'good',
    refreshToken: 'refresh-good',
  });
  await client.logout();

  assert.equal(client.accessToken, null);
  assert.deepEqual(
    state.calls.map((call) => `${call.method} ${call.path}`),
    ['POST /api/auth/logout/'],
  );
});

test('недоступная платформа даёт network_error, а не TypeError', async () => {
  const client = new AuraClient({
    baseUrl,
    token: 'good',
    fetch: async () => {
      throw new Error('нет сети');
    },
  });

  await assert.rejects(
    client.projects(),
    (error) => {
      assert.ok(error instanceof AuraApiError);
      assert.equal(error.status, 0);
      assert.equal(error.code, 'network_error');
      return true;
    },
  );
});
