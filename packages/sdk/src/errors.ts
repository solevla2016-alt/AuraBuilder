/**
 * Ошибки публичного API.
 *
 * Конверт `{error: {code, message}}` — часть контракта v1, но вход и
 * обновление токена живут во внутреннем `/api/auth/` и отвечают полями
 * DRF. Поэтому разбор здесь терпимый: клиенту нужны `status` и `code`,
 * а не точная форма конкретного эндпоинта.
 */

const STATUS_CODES: Readonly<Record<number, string>> = {
  400: 'invalid_request',
  401: 'unauthorized',
  402: 'payment_required',
  403: 'forbidden',
  404: 'not_found',
  405: 'method_not_allowed',
  409: 'conflict',
  413: 'payload_too_large',
  422: 'unprocessable',
  429: 'rate_limited',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function firstMessage(value: unknown): string | null {
  if (typeof value === 'string' && value !== '') return value;
  if (Array.isArray(value)) {
    const first = value[0];
    if (typeof first === 'string' && first !== '') return first;
  }
  return null;
}

export class AuraApiError extends Error {
  /** HTTP-статус; 0 — запрос не дошёл до платформы. */
  readonly status: number;
  /** Стабильный код: `not_found`, `forbidden`, `network_error` и т. п. */
  readonly code: string;
  /** Поля конверта: например, `reason` у ответа 402. */
  readonly details: Readonly<Record<string, unknown>>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'AuraApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  static fromResponse(status: number, raw: string): AuraApiError {
    const fallbackCode = STATUS_CODES[status] ?? 'error';
    const fallbackMessage =
      status === 0 ? 'Нет связи с платформой.' : `Ошибка ${status}.`;

    let body: unknown = null;
    if (raw !== '') {
      try {
        body = JSON.parse(raw);
      } catch {
        body = null;
      }
    }
    if (!isRecord(body)) {
      return new AuraApiError(status, fallbackCode, fallbackMessage);
    }

    const envelope = body['error'];
    if (isRecord(envelope)) {
      const code =
        typeof envelope['code'] === 'string' ? envelope['code'] : fallbackCode;
      const message =
        typeof envelope['message'] === 'string'
          ? envelope['message']
          : fallbackMessage;
      return new AuraApiError(status, code, message, envelope);
    }

    const detail = firstMessage(body['detail']);
    if (detail !== null) {
      return new AuraApiError(status, fallbackCode, detail, body);
    }
    // Ошибки DRF: `{"non_field_errors": [...]}` или `{"поле": [...]}`.
    for (const value of Object.values(body)) {
      const message = firstMessage(value);
      if (message !== null) {
        return new AuraApiError(status, fallbackCode, message, body);
      }
    }
    return new AuraApiError(status, fallbackCode, fallbackMessage);
  }
}
