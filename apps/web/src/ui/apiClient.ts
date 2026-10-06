/**
 * Общий слой запросов к Control Plane.
 *
 * Вынесен отдельно от api.ts, потому что запросы идут не только оттуда:
 * узлы данных (data.ts) тоже нуждаются в заголовке авторизации и в
 * обновлении истёкшего токена. Две копии этого кода разъедутся при
 * первой же правке.
 *
 * Токены лежат в localStorage, а не в памяти модуля.
 *
 * Память переживает только одну вкладку: открыли вторую, вышли в
 * первой — вторая осталась бы с рабочим интерфейсом, но каждый запрос
 * падал бы в 401, и пользователь увидел бы «работа не сохраняется».
 *
 * Риск XSS для токена здесь принят осознанно: HttpOnly-cookie в
 * конфигурации «фронт и API на одном домене» означала бы, что любая
 * инъекция в редакторе крадёт и сессию, а страховка с CSRF этот случай
 * не покрывает. Перед этапом 10 (пентест) схему нужно пересмотреть
 * вместе с настройками развёртывания.
 */

/**
 * Адрес Control Plane. Задаётся переменной окружения: без неё фронт
 * и API лежат на одном домене и путь относительный.
 */
export const BASE = (import.meta.env['VITE_API_BASE'] as string | undefined) ?? '/api';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
  };

  // Access-токен живёт 15 минут (ТЗ п.7.7), поэтому при каждом запросе
  // access мог уже истечь. Ответ 401 с кодом token_not_valid
  // означает «обновить и повторить», а не «иди на страницу входа»:
  // иначе пользователь посреди правки вылетал бы из редактора.
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res = await fetch(`${BASE}${path}`, { ...init, headers });

  if (res.status === 401 && token && getRefreshToken()) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getAccessToken()}`;
      res = await fetch(`${BASE}${path}`, { ...init, headers });
    }
  }

  if (!res.ok) {
    // Текст ошибки с сервера полезнее «500»: он уже провалидирован.
    let detail = `${res.status}`;
    try {
      const body = (await res.json()) as unknown;
      detail = extractDetail(body) ?? detail;
    } catch {
      // ответ не JSON — оставляем код
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * Достаёт сообщение об ошибке из ответа DRF.
 *
 * DRF отвечает двумя разными форматами: «detail» для ошибок уровня
 * запроса и словарь полей для ошибок валидации формы
 * ({username: ["Логин уже занят."]}). Раньше читался только detail,
 * поэтому «Логин уже занят» превращался в безликое «400».
 */
function extractDetail(body: unknown): string | null {
  if (typeof body === 'string') return body;
  if (body === null || typeof body !== 'object') return null;

  const record = body as Record<string, unknown>;
  if (typeof record['detail'] === 'string') return record['detail'];

  const parts: string[] = [];
  for (const value of Object.values(record)) {
    if (Array.isArray(value)) {
      const text = value.filter((v) => typeof v === 'string').join(' ');
      if (text) parts.push(text);
    } else if (typeof value === 'string') {
      parts.push(value);
    }
  }
  return parts.length > 0 ? parts.join(' ') : null;
}

/* ------------------------------------------------------------------ */
/*  Токены                                                             */
/* ------------------------------------------------------------------ */

/*
 * Память переживает только одну вкладку: открыли вторую, вышел в
 * первой — вторая осталась бы с рабочим интерфейсом, но каждый запрос
 * падал бы в 401, и пользователь увидел бы «работа не сохраняется».
 *
 * Риск XSS для токена здесь принят осознанно: HttpOnly-cookie в
 * конфигурации «фронт и API на одном домене» означала бы, что любая
 * инъекция в редакторе крадёт и сессию, а страховка с CSRF не
 * покрывает этот случай. Перед этапом 10 (пентест) схему нужно
 * пересмотреть вместе с настройками развёртывания.
 */
const ACCESS_KEY = 'aurabuilder.access';
const REFRESH_KEY = 'aurabuilder.refresh';

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

/**
 * Обновление пары токенов. Ротация означает, что старый refresh
 * после использования не работает, поэтому параллельные обновления
 * из двух вкладок заканчиваются одной ошибкой. Обещание общее на
 * модуль: второй вызов ждёт результат первого, а не тратит свой
 * refresh впустую.
 */
let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const refresh = getRefreshToken();
    if (!refresh) return false;
    try {
      const res = await fetch(`${BASE}/auth/refresh/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      });
      if (!res.ok) {
        // Refresh недействителен: значит, его отозвали или срок вышел.
        // Молча продолжать нельзя — следующий запрос снова получит 401.
        clearTokens();
        notifySessionExpired();
        return false;
      }
      const body = (await res.json()) as { access: string; refresh?: string };
      localStorage.setItem(ACCESS_KEY, body.access);
      // Сервер может не прислать новый refresh, если ротация выключена.
      if (body.refresh) localStorage.setItem(REFRESH_KEY, body.refresh);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/** Подписчики на истечение сессии — в редакторе это выход на экран входа. */
type SessionListener = () => void;
const sessionListeners = new Set<SessionListener>();

export function onSessionExpired(listener: SessionListener): () => void {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

function notifySessionExpired(): void {
  for (const listener of sessionListeners) listener();
}

/** Токены уже получены (проверка при старте редактора). */
export function hasSession(): boolean {
  return getAccessToken() !== null;
}
