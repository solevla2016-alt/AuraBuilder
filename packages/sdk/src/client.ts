/**
 * Клиент публичного API AuraBuilder.
 *
 * Зависимостей нет: используется `fetch` и `Headers` из платформы, а
 * сборка не тянет ничего лишнего. Это требование ТЗ п.16.4 — клиент
 * должен работать там, где нет npm-реестра и самой AuraBuilder.
 *
 * `baseUrl` — адрес платформы без `/api`: методы сами добавляют
 * `/api/v1/` или `/api/auth/`. Так вызывающий код не склеивает пути
 * руками и не получает двойные слэши.
 *
 * Access-токен живёт 15 минут, поэтому при 401 клиент один раз
 * обновляет его refresh-токеном и повторяет запрос. Без этого каждая
 * интеграция писала бы один и тот же перехватчик.
 */

import { AuraApiError } from './errors.js';
import type {
  ApiDescription,
  ExportedArchive,
  LoginResult,
  PageDetail,
  PageList,
  Paginated,
  ProjectDetail,
  ProjectSummary,
  TokenPair,
  VersionList,
} from './types.js';

const API = '/api/v1';
const AUTH = '/api/auth';

/** Подмена `fetch` для тестов и нестандартных окружений. */
export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

export interface AuraClientOptions {
  /** Адрес платформы: `https://aura.example`, без `/api`. */
  baseUrl: string;
  token?: string;
  refreshToken?: string;
  fetch?: FetchLike;
}

export interface ListOptions {
  limit?: number;
  offset?: number;
}

export interface ExportOptions {
  /** Номер снимка. По умолчанию — последний сохранённый. */
  version?: number;
  /** Собрать архив с PWA-обвязкой. */
  pwa?: boolean;
  /** Базовый адрес сайта для абсолютных ссылок в архиве. */
  baseUrl?: string;
}

function queryString(
  params: Readonly<Record<string, string | number | undefined>>,
): string {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined) query.set(name, String(value));
  }
  const text = query.toString();
  return text === '' ? '' : `?${text}`;
}

function filenameOf(disposition: string | null): string | null {
  if (disposition === null) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const encodedName = encoded?.[1];
  if (encodedName !== undefined) {
    try {
      return decodeURIComponent(encodedName);
    } catch {
      return null;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain?.[1] ?? null;
}

function intHeader(value: string | null): number | null {
  if (value === null) return null;
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? number : null;
}

export class AuraClient {
  readonly baseUrl: string;

  private token: string | null;
  private refreshToken: string | null;
  private readonly fetchImpl: FetchLike;
  /**
   * Общий запрос обновления. При ротации refresh второй параллельный
   * запрос со старым токеном получил бы 401 и «разлогинил» клиента,
   * поэтому одновременные 401 ждут один и тот же refresh.
   */
  private refreshing: Promise<TokenPair> | null = null;

  constructor(options: AuraClientOptions) {
    const base = options.baseUrl.trim().replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(base)) {
      throw new Error('baseUrl должен начинаться с http:// или https://');
    }
    this.baseUrl = base;
    this.token = options.token ?? null;
    this.refreshToken = options.refreshToken ?? null;
    this.fetchImpl =
      options.fetch ?? ((url, init) => globalThis.fetch(url, init));
  }

  /** Текущий access-токен или null, если вход не выполнен. */
  get accessToken(): string | null {
    return this.token;
  }

  /**
   * Заменить токены вручную: например, после входа в своём интерфейсе.
   * `refresh` можно не передавать, если он не менялся.
   */
  setTokens(access: string | null, refresh?: string | null): void {
    this.token = access;
    if (refresh !== undefined) this.refreshToken = refresh;
  }

  /** Описание контракта: версия, способы входа, пределы пагинации. */
  describe(): Promise<ApiDescription> {
    return this.get<ApiDescription>(`${API}/`);
  }

  /** Вход по логину или email. Токены сохраняются в клиенте. */
  async login(login: string, password: string): Promise<LoginResult> {
    const result = await this.post<LoginResult>(`${AUTH}/login/`, {
      login,
      password,
    });
    this.token = result.access;
    this.refreshToken = result.refresh;
    return result;
  }

  /**
   * Обновить access-токен. При включённой ротации сервер присылает и
   * новый refresh — клиент сохраняет его сам. Параллельные вызовы
   * ждут один запрос: второй refresh со старым токеном уже не пройдёт.
   */
  refresh(): Promise<TokenPair> {
    const pending =
      this.refreshing ??
      this.performRefresh().finally(() => {
        this.refreshing = null;
      });
    this.refreshing = pending;
    return pending;
  }

  private async performRefresh(): Promise<TokenPair> {
    const current = this.refreshToken;
    if (current === null) {
      throw new AuraApiError(
        401,
        'unauthorized',
        'Нет refresh-токена: сначала войдите.',
      );
    }
    const pair = await this.post<TokenPair>(`${AUTH}/refresh/`, {
      refresh: current,
    });
    this.token = pair.access;
    if (pair.refresh !== undefined) this.refreshToken = pair.refresh;
    return pair;
  }

  /**
   * Выход: сервер отзывает refresh, клиент забывает оба токена.
   * Ошибка сети не мешает выходу — иначе недоступная платформа
   * оставляла бы человека «в системе» на его же устройстве.
   */
  async logout(): Promise<void> {
    const refresh = this.refreshToken;
    try {
      if (refresh !== null) {
        await this.send(
          `${AUTH}/logout/`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh }),
          },
          false,
        );
      }
    } catch {
      // Выход важнее ответа сервера.
    } finally {
      this.token = null;
      this.refreshToken = null;
    }
  }

  /** Проекты, которые пользователь может открыть. */
  projects(
    options: ListOptions = {},
  ): Promise<Paginated<ProjectSummary>> {
    return this.get<Paginated<ProjectSummary>>(
      `${API}/projects/${queryString({
        limit: options.limit,
        offset: options.offset,
      })}`,
    );
  }

  /** Проект целиком: главная страница, дополнительные и оформление. */
  project(projectId: string): Promise<ProjectDetail> {
    return this.get<ProjectDetail>(this.projectPath(projectId));
  }

  /** Все страницы, включая главную, без деревьев. */
  pages(projectId: string): Promise<PageList> {
    return this.get<PageList>(`${this.projectPath(projectId)}pages/`);
  }

  /**
   * Страница с деревом блоков. Главная отдельной записью не отдаётся:
   * её дерево уже пришло в `project()`.
   */
  page(projectId: string, slug: string): Promise<PageDetail> {
    if (slug === '') {
      throw new Error(
        'Пустой slug — это главная: её дерево возвращает project().',
      );
    }
    return this.get<PageDetail>(
      `${this.projectPath(projectId)}pages/${encodeURIComponent(slug)}/`,
    );
  }

  /** Снимки проекта без деревьев: история выбора версии. */
  versions(projectId: string): Promise<VersionList> {
    return this.get<VersionList>(`${this.projectPath(projectId)}versions/`);
  }

  /**
   * Статический архив. Возвращает байты, а не Blob: в Node нет Blob
   * как файла, а вызывающий сам решит, писать его на диск или отдавать
   * дальше.
   */
  async exportArchive(
    projectId: string,
    options: ExportOptions = {},
  ): Promise<ExportedArchive> {
    const query = queryString({
      version: options.version,
      pwa: options.pwa === true ? '1' : undefined,
      baseUrl: options.baseUrl,
    });
    const response = await this.send(
      `${this.projectPath(projectId)}export/${query}`,
      { method: 'GET' },
    );
    if (!response.ok) return this.payload<never>(response);

    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      bytes,
      filename: filenameOf(response.headers.get('Content-Disposition'))
        ?? 'project-static.zip',
      contentType: response.headers.get('Content-Type') ?? 'application/zip',
      version: intHeader(response.headers.get('X-AuraBuilder-Version')),
      warnings:
        intHeader(response.headers.get('X-AuraBuilder-Warnings')) ?? 0,
      pwa: response.headers.get('X-AuraBuilder-PWA') === '1',
    };
  }

  private projectPath(projectId: string): string {
    return `${API}/projects/${encodeURIComponent(projectId)}/`;
  }

  private async get<T>(path: string): Promise<T> {
    const response = await this.send(path, { method: 'GET' });
    return this.payload<T>(response);
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const response = await this.send(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return this.payload<T>(response);
  }

  /**
   * Запрос с авторизацией. На 401 один раз пробует refresh: токен
   * живёт 15 минут, и интеграция не должна падать от истечения срока.
   */
  private async send(
    path: string,
    init: RequestInit,
    retry = true,
  ): Promise<Response> {
    const headers = new Headers(init.headers);
    if (!headers.has('Accept')) headers.set('Accept', 'application/json');
    if (this.token !== null) {
      headers.set('Authorization', `Bearer ${this.token}`);
    }

    let response: Response;
    try {
      response = await this.fetchImpl(this.url(path), { ...init, headers });
    } catch (error) {
      throw new AuraApiError(
        0,
        'network_error',
        error instanceof Error ? error.message : 'Нет связи с платформой.',
        { path },
      );
    }

    if (
      response.status === 401 &&
      retry &&
      this.refreshToken !== null &&
      !path.startsWith(AUTH)
    ) {
      const refreshed = await this.refresh().then(
        () => true,
        () => false,
      );
      if (refreshed) return this.send(path, init, false);
    }
    return response;
  }

  private url(path: string): string {
    if (/^https?:\/\//i.test(path)) return path;
    return `${this.baseUrl}${path}`;
  }

  /** Разбор ответа: конверт ошибки или JSON. */
  private async payload<T>(response: Response): Promise<T> {
    const raw = await response.text();
    if (!response.ok) {
      throw AuraApiError.fromResponse(response.status, raw);
    }
    if (raw === '') return undefined as T;
    try {
      return JSON.parse(raw) as T;
    } catch {
      throw new AuraApiError(
        response.status,
        'invalid_response',
        'Ответ платформы не является JSON.',
      );
    }
  }
}
