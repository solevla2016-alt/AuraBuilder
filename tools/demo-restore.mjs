/**
 * Проверка отката к резервной копии на живом стенде.
 *
 * Зачем: сервис и API покрыты тестами, но откат меняет то, что
 * увидит посетитель, и это стоит увидеть настоящим запросом к
 * опубликованному сайту.
 *
 *   node tools/demo-restore.mjs http://127.0.0.1:8080/
 */

const BASE = process.argv[2] ?? 'http://127.0.0.1:8080/';
const API = `${BASE.replace(/\/$/, '')}/api`;
const LOGIN = 'restore-check';
const PASSWORD = 'Verysecret123';

async function call(path, { method = 'GET', body, token } = {}) {
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  const parsed = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}: ${text.slice(0, 160)}`);
  return parsed;
}

const main = async () => {
  const login = await call('/auth/login/', { method: 'POST', body: { login: LOGIN, password: PASSWORD } }).catch(
    async () => {
      await call('/auth/register/', {
        method: 'POST',
        body: { username: LOGIN, email: `${LOGIN}@example.com`, password: PASSWORD, consent_pdn: true },
      });
      return call('/auth/login/', { method: 'POST', body: { login: LOGIN, password: PASSWORD } });
    },
  );
  const token = login.access;
  await call('/billing/subscription/change/', { method: 'POST', body: { plan: 'business' }, token }).catch(() => {});

  const project = await call('/projects/', {
    method: 'POST',
    body: { name: 'Проверка отката', slug: `rollback-${Date.now().toString(36).slice(-6)}` },
    token,
  });
  const pid = project.id;

  await call(`/projects/${pid}/`, {
    method: 'PATCH',
    token,
    body: { tree: { version: 1, width: 800, settings: {}, blocks: [
      { id: 'b1', module: 'text.heading', x: 0, y: 0, width: 700, height: 80,
        label: 'Первый', props: { text: 'Состояние первое' } },
    ] } },
  });
  const first = await call(`/projects/${pid}/versions/`, { method: 'POST', body: { label: 'v1' }, token });
  const site = await call(`/projects/${pid}/site/`, { method: 'POST', body: {}, token });
  console.log(`сайт: ${site.url}`);

  const siteText = async () => {
    const res = await fetch(`${BASE.replace(/\/$/, '')}${site.url}`);
    return res.ok ? res.text() : `HTTP ${res.status}`;
  };
  console.log('до копии содержит «первое»:', (await siteText()).includes('Состояние первое'));

  const backup = await call(`/projects/${pid}/site/backup/`, { method: 'POST', body: {}, token });
  console.log(`копия версии ${backup.number} сделана`);

  // Меняем содержимое и публикуем заново.
  await call(`/projects/${pid}/`, {
    method: 'PATCH',
    token,
    body: { tree: { version: 1, width: 800, settings: {}, blocks: [
      { id: 'b1', module: 'text.heading', x: 0, y: 0, width: 700, height: 80,
        label: 'Второй', props: { text: 'Состояние второе' } },
    ] } },
  });
  await call(`/projects/${pid}/versions/`, { method: 'POST', body: { label: 'v2' }, token });
  await call(`/projects/${pid}/site/`, { method: 'POST', body: {}, token });
  console.log('после публикации содержит «второе»:', (await siteText()).includes('Состояние второе'));

  const list = await call(`/projects/${pid}/site/backups/`, { token });
  console.log('копий в списке:', list.backups.length, '| восстановима:', list.backups[0]?.restorable);

  await call(`/projects/${pid}/site/backups/${list.backups[0].id}/restore/`, { method: 'POST', body: {}, token });
  const after = await siteText();
  console.log('после отката содержит «первое»:', after.includes('Состояние первое'));
  console.log('после отката содержит «второе»:', after.includes('Состояние второе'));
  console.log(`версия ${first.number} была до отката`);
};

main().catch((e) => {
  console.error('не получилось:', e.message);
  process.exitCode = 1;
});