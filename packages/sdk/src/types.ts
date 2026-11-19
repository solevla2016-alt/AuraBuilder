/**
 * Формы ответов публичного API v1.
 *
 * Типы повторяют `apps/api_v1/payloads.py` один в один: SDK не
 * переименовывает поля и не «улучшает» их. Иначе интеграция,
 * написанная по типам, падала бы на живом ответе — а обещание
 * «клиент с типами» держится только на совпадении с сервером.
 *
 * Дерево блоков намеренно не разобрано (`BlockTree`): его структура
 * принадлежит редактору и меняется без смены версии API.
 */

/** Роль пользователя в проекте. */
export type ProjectRole = 'owner' | 'admin' | 'editor' | 'dev' | 'viewer';

/** Оформление проекта. Пустая строка — значение по умолчанию. */
export interface ProjectBrand {
  accent: string;
  font: string;
  signature: string;
  utmSource: string;
  utmMedium: string;
  utmCampaign: string;
}

/** Дерево блоков. SDK передаёт его как есть, не заглядывая внутрь. */
export type BlockTree = Record<string, unknown>;

export interface ProjectSummary {
  id: string;
  name: string;
  version: number;
  /** null, если проект доступен только на чтение без роли. */
  role: ProjectRole | null;
  blockCount: number;
  pageCount: number;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  brand: ProjectBrand;
  /** Дерево главной страницы: она хранится в проекте, а не в Page. */
  tree: BlockTree;
  pages: PageSummary[];
}

export interface PageSummary {
  /** null у главной страницы: отдельной записи Page для неё нет. */
  id: string | null;
  /** Пустая строка — главная страница. */
  slug: string;
  title: string;
  seoTitle: string;
  seoDescription: string;
  blockCount: number;
  version: number;
  updatedAt: string | null;
  isHome: boolean;
}

export interface PageDetail extends PageSummary {
  tree: BlockTree;
}

export interface VersionSummary {
  number: number;
  label: string;
  createdAt: string | null;
  blockCount: number;
  /** Главная плюс дополнительные страницы на момент снимка. */
  pageCount: number;
}

export interface PageList {
  projectId: string;
  pages: PageSummary[];
}

export interface VersionList {
  projectId: string;
  versions: VersionSummary[];
}

export interface PaginationMeta {
  total: number;
  limit: number;
  offset: number;
}

export interface Paginated<T> {
  data: T[];
  meta: PaginationMeta;
}

export interface ApiEndpoint {
  method: string;
  path: string;
}

/** Ответ `/api/v1/`: контракт, версия и способы входа. */
export interface ApiDescription {
  apiVersion: number;
  service: string;
  auth: {
    type: 'bearer';
    obtain: string;
    refresh: string;
  };
  endpoints: ApiEndpoint[];
  pagination: {
    limit: { default: number; max: number };
    offset: { default: number };
  };
  mcp: {
    endpoint: string;
    transport: string;
    sse: boolean;
  };
}

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

export interface LoginResult {
  access: string;
  refresh: string;
  user: AuthUser;
}

/** Ответ обновления токена. При ротации refresh приходит новым. */
export interface TokenPair {
  access: string;
  refresh?: string;
}

/** Выгруженный статический архив. */
export interface ExportedArchive {
  /** Содержимое zip. Uint8Array работает и в браузере, и в Node. */
  bytes: Uint8Array;
  filename: string;
  contentType: string;
  /** Номер версии из заголовка ответа, если сервер его прислал. */
  version: number | null;
  warnings: number;
  pwa: boolean;
}
