/**
 * Проверка подписи сверяется с независимой реализацией из node:crypto:
 * если обе считают одинаково, SDK понимает формат платформы, а не
 * «свой собственный».
 */

import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { test } from 'node:test';

import {
  WEBHOOK_EVENT_KINDS,
  WEBHOOK_EVENT_LABELS,
  WebhookPayloadError,
  WebhookSignatureError,
  parseWebhook,
  verifySignature,
  verifyWebhook,
} from '../dist/index.js';

const secret = 's3cret-webhook-key';
const payload = {
  delivery: 'd-1',
  webhook: 'w-1',
  project: { id: 'p-1', name: 'Лендинг' },
  event: {
    id: 'e-1',
    kind: 'publish',
    status: 'ok',
    message: 'Сайт опубликован: версия 7.',
    actor: 'owner',
    createdAt: '2026-02-01T10:00:00+00:00',
  },
  sentAt: '2026-02-01T10:00:01+00:00',
};

const body = JSON.stringify(payload);

function signatureOf(text, key = secret) {
  return `sha256=${createHmac('sha256', key).update(text, 'utf8').digest('hex')}`;
}

test('подпись совпадает с node:crypto', async () => {
  assert.equal(
    await verifySignature({ secret, body, signature: signatureOf(body) }),
    true,
  );
});

test('подпись считается по байтам, а не по строке после JSON.parse', async () => {
  const bytes = new TextEncoder().encode(body);
  assert.equal(
    await verifySignature({
      secret,
      body: bytes,
      signature: signatureOf(body),
    }),
    true,
  );
  assert.equal(
    await verifySignature({
      secret,
      body: bytes.buffer,
      signature: signatureOf(body),
    }),
    true,
  );

  // Тот же смысл, другой порядок ключей — байты уже не те.
  const reordered = JSON.stringify({
    sentAt: payload.sentAt,
    event: payload.event,
    project: payload.project,
    webhook: payload.webhook,
    delivery: payload.delivery,
  });
  assert.equal(
    await verifySignature({
      secret,
      body: reordered,
      signature: signatureOf(body),
    }),
    false,
  );
});

test('подмена тела, чужой секрет и порча подписи отвергаются', async () => {
  const valid = signatureOf(body);
  assert.equal(
    await verifySignature({
      secret,
      body: body.replace('версия 7', 'версия 8'),
      signature: valid,
    }),
    false,
  );
  assert.equal(
    await verifySignature({
      secret: 'другой-секрет',
      body,
      signature: valid,
    }),
    false,
  );
  assert.equal(
    await verifySignature({
      secret,
      body,
      signature: `${valid.slice(0, -2)}00`,
    }),
    false,
  );
});

test('неверный формат заголовка — это false, а не исключение', async () => {
  const hex = signatureOf(body).slice('sha256='.length);
  const variants = [
    '',
    'sha256=',
    hex,
    `md5=${hex}`,
    `sha256=${hex.slice(2)}`,
    'sha256=zz',
    `sha256=${hex}extra`,
  ];
  for (const variant of variants) {
    assert.equal(
      await verifySignature({ secret, body, signature: variant }),
      false,
      variant,
    );
  }
});

test('префикс и hex принимаются в любом регистре', async () => {
  const hex = signatureOf(body).slice('sha256='.length).toUpperCase();
  assert.equal(
    await verifySignature({ secret, body, signature: `SHA256=${hex}` }),
    true,
  );
});

test('пустой секрет — ошибка настройки, а не «подпись не сошлась»', async () => {
  await assert.rejects(
    verifySignature({ secret: '', body, signature: signatureOf(body) }),
    /Секрет подписи пуст/,
  );
});

test('verifyWebhook разбирает событие после проверки подписи', async () => {
  const parsed = await verifyWebhook({
    secret,
    body,
    signature: signatureOf(body),
  });
  assert.deepEqual(parsed, payload);
});

test('verifyWebhook не разбирает тело с неверной подписью', async () => {
  await assert.rejects(
    verifyWebhook({
      secret,
      body,
      signature: signatureOf(body, 'чужой'),
    }),
    (error) => error instanceof WebhookSignatureError,
  );
});

test('parseWebhook отвергает чужой вид и статус события', () => {
  const unknownKind = structuredClone(payload);
  unknownKind.event.kind = 'teleport';
  assert.throws(
    () => parseWebhook(JSON.stringify(unknownKind)),
    (error) =>
      error instanceof WebhookPayloadError && /вид события/.test(error.message),
  );

  const unknownStatus = structuredClone(payload);
  unknownStatus.event.status = 'maybe';
  assert.throws(
    () => parseWebhook(JSON.stringify(unknownStatus)),
    (error) => error instanceof WebhookPayloadError,
  );
});

test('parseWebhook отвергает не JSON и тело без проекта', () => {
  assert.throws(() => parseWebhook('не json'), WebhookPayloadError);
  assert.throws(
    () => parseWebhook(JSON.stringify({ delivery: 'd-1' })),
    /project/,
  );
});

test('каталог видов событий совпадает с сервером', () => {
  assert.deepEqual([...WEBHOOK_EVENT_KINDS], [
    'build',
    'publish',
    'withdraw',
    'backup',
    'restore',
    'deploy',
    'schedule',
    'review',
  ]);
  assert.deepEqual(
    Object.keys(WEBHOOK_EVENT_LABELS),
    [...WEBHOOK_EVENT_KINDS],
  );

  for (const kind of WEBHOOK_EVENT_KINDS) {
    const variant = structuredClone(payload);
    variant.event.kind = kind;
    assert.equal(parseWebhook(JSON.stringify(variant)).event.kind, kind);
  }
});
