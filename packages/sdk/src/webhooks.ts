/**
 * Проверка подписи и разбор вебхуков AuraBuilder.
 *
 * Подпись считается по точным байтам тела, а не по разобранному JSON:
 * получатель должен передать сюда тело до `JSON.parse`, иначе порядок
 * ключей и пробелы уже другие, и подпись не сойдётся. Сравнение делает
 * WebCrypto (`subtle.verify`), поэтому оно не зависит от нашего кода
 * сравнения строк и не утекает по времени.
 *
 * Зависимостей нет: WebCrypto есть и в браузере, и в Node 20+.
 */

/** Заголовок с подписью: `sha256=<hex>`. */
export const WEBHOOK_SIGNATURE_HEADER = 'X-Aura-Signature';
/** Заголовок с видом события — для маршрутизации без разбора тела. */
export const WEBHOOK_EVENT_HEADER = 'X-Aura-Event';
/** Идентификатор доставки: им отбрасывается повтор. */
export const WEBHOOK_DELIVERY_HEADER = 'X-Aura-Delivery';

/** Виды событий совпадают с `ProjectEvent.KIND_CHOICES`. */
export const WEBHOOK_EVENT_KINDS = [
  'build',
  'publish',
  'withdraw',
  'backup',
  'restore',
  'deploy',
  'schedule',
  'review',
] as const;

export type WebhookEventKind = (typeof WEBHOOK_EVENT_KINDS)[number];

export type WebhookEventStatus = 'ok' | 'failed' | 'info';

/** Подписи для журнала интеграции. Не влияют на проверку подписи. */
export const WEBHOOK_EVENT_LABELS: Readonly<Record<WebhookEventKind, string>> = {
  build: 'Сборка',
  publish: 'Публикация',
  withdraw: 'Отзыв',
  backup: 'Резервная копия',
  restore: 'Восстановление',
  deploy: 'Деплой',
  schedule: 'Отложенная публикация',
  review: 'Согласование',
};

export interface WebhookProject {
  id: string;
  name: string;
}

export interface WebhookEvent {
  id: string;
  kind: WebhookEventKind;
  status: WebhookEventStatus;
  message: string;
  /** Логин автора события; null у системных действий. */
  actor: string | null;
  createdAt: string;
}

/** Тело запроса, которое присылает платформа. */
export interface WebhookPayload {
  delivery: string;
  webhook: string;
  project: WebhookProject;
  event: WebhookEvent;
  sentAt: string;
}

/** Тело может быть строкой, байтами или буфером — важен точный набор байтов. */
export type WebhookBody = string | Uint8Array | ArrayBuffer;

export interface VerifySignatureOptions {
  secret: string;
  body: WebhookBody;
  /** Значение заголовка `X-Aura-Signature` как есть. */
  signature: string;
}

export class WebhookSignatureError extends Error {
  constructor(message = 'Подпись вебхука не сходится.') {
    super(message);
    this.name = 'WebhookSignatureError';
  }
}

export class WebhookPayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'WebhookPayloadError';
  }
}

function bodyBytes(body: WebhookBody): Uint8Array {
  if (typeof body === 'string') return new TextEncoder().encode(body);
  return body instanceof Uint8Array ? body : new Uint8Array(body);
}

function bodyText(body: WebhookBody): string {
  if (typeof body === 'string') return body;
  return new TextDecoder().decode(bodyBytes(body));
}

/**
 * Копия в собственный ArrayBuffer: `subtle` не принимает буфер,
 * разделяемый с другой памятью, и так мы не зависим от версии lib.dom.
 */
function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(copy).set(bytes);
  return copy;
}

function hexToBytes(hex: string): Uint8Array | null {
  if (hex === '' || hex.length % 2 !== 0) return null;
  if (!/^[0-9a-fA-F]+$/.test(hex)) return null;
  const bytes = new Uint8Array(hex.length / 2);
  for (let index = 0; index < bytes.length; index += 1) {
    const pair = hex.slice(index * 2, index * 2 + 2);
    bytes[index] = Number.parseInt(pair, 16);
  }
  return bytes;
}

/**
 * true — подпись верна. false — любая причина: не тот заголовок,
 * неверный формат, чужой секрет или изменённое тело. Причину не
 * различаем намеренно: приёмнику достаточно ответить 400.
 */
export async function verifySignature(
  options: VerifySignatureOptions,
): Promise<boolean> {
  if (options.secret === '') {
    throw new Error('Секрет подписи пуст: проверьте настройки приёмника.');
  }

  const signature = options.signature.trim();
  const marker = signature.indexOf('=');
  if (marker === -1) return false;
  const scheme = signature.slice(0, marker).trim().toLowerCase();
  const value = signature.slice(marker + 1).trim();
  if (scheme !== 'sha256' || value === '') return false;

  const signatureBytes = hexToBytes(value);
  if (signatureBytes === null) return false;

  const subtle = globalThis.crypto?.subtle;
  if (subtle === undefined) {
    throw new Error(
      'WebCrypto недоступен: проверка подписи требует https или Node 20+.',
    );
  }

  const key = await subtle.importKey(
    'raw',
    toArrayBuffer(new TextEncoder().encode(options.secret)),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['verify'],
  );
  return subtle.verify(
    'HMAC',
    key,
    toArrayBuffer(signatureBytes),
    toArrayBuffer(bodyBytes(options.body)),
  );
}

/**
 * Проверяет подпись и разбирает тело. Порядок важен: сначала подпись,
 * потом JSON — иначе пришлось бы разбирать данные, которым ещё не
 * доверяем.
 */
export async function verifyWebhook(
  options: VerifySignatureOptions,
): Promise<WebhookPayload> {
  if (!(await verifySignature(options))) {
    throw new WebhookSignatureError();
  }
  return parseWebhook(options.body);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(
  source: Record<string, unknown>,
  field: string,
  allowEmpty = false,
): string {
  const value = source[field];
  if (typeof value !== 'string' || (!allowEmpty && value === '')) {
    throw new WebhookPayloadError(
      `Поле ${field} должно быть ${allowEmpty ? 'строкой' : 'непустой строкой'}.`,
    );
  }
  return value;
}

function nullableText(
  source: Record<string, unknown>,
  field: string,
): string | null {
  const value = source[field];
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') {
    throw new WebhookPayloadError(`Поле ${field} должно быть строкой или null.`);
  }
  return value;
}

/**
 * Разбор тела вебхука с проверкой обязательных полей. Неизвестные
 * поля сохраняются сервером на будущее, поэтому лишнее не отвергаем.
 */
export function parseWebhook(body: WebhookBody): WebhookPayload {
  let data: unknown;
  try {
    data = JSON.parse(bodyText(body));
  } catch {
    throw new WebhookPayloadError('Тело вебхука не является JSON.');
  }
  if (!isRecord(data)) {
    throw new WebhookPayloadError('Тело вебхука должно быть объектом.');
  }

  const project = data['project'];
  if (!isRecord(project)) {
    throw new WebhookPayloadError('Нет объекта project.');
  }
  const event = data['event'];
  if (!isRecord(event)) {
    throw new WebhookPayloadError('Нет объекта event.');
  }

  const kind = text(event, 'kind');
  if (!(WEBHOOK_EVENT_KINDS as readonly string[]).includes(kind)) {
    throw new WebhookPayloadError(`Неизвестный вид события: ${kind}.`);
  }
  const status = text(event, 'status');
  if (!['ok', 'failed', 'info'].includes(status)) {
    throw new WebhookPayloadError(`Неизвестный статус события: ${status}.`);
  }

  return {
    delivery: text(data, 'delivery'),
    webhook: text(data, 'webhook'),
    project: {
      id: text(project, 'id'),
      name: text(project, 'name'),
    },
    event: {
      id: text(event, 'id'),
      kind: kind as WebhookEventKind,
      status: status as WebhookEventStatus,
      message: text(event, 'message', true),
      actor: nullableText(event, 'actor'),
      createdAt: text(event, 'createdAt'),
    },
    sentAt: text(data, 'sentAt'),
  };
}
