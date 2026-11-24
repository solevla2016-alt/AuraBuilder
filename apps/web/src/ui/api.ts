/**
 * Клиент Control Plane.
 *
 * Минимальный набор для вертикального среза: получить проект и сохранить
 * дерево. Адрес берётся из переменной окружения, чтобы не хардкодить
 * порт и не сломать стенд 1С на другом хосте.
 *
 * Токены авторизации подключаются на этапе 2 (роли и права по ТЗ п.11.1);
 * сейчас запросы идут без них, как и предполагает стенд.
 */

import type { DocumentVersionRow, Project, ProjectBrand, ProjectPage } from './project';
import { BASE, request, setTokens, getRefreshToken, clearTokens } from './apiClient';

// Общий слой запросов живёт в apiClient.ts: узлы данных ходят в API
// так же и должны делить с ними обновление токенов.
export {
  ApiError,
  getAccessToken,
  getRefreshToken,
  setTokens,
  clearTokens,
  onSessionExpired,
  hasSession,
} from './apiClient';
import type { CategoryDef, ModuleDef } from './moduleRegistry';

export interface ModuleCatalog {
  total: number;
  categories: CategoryDef[];
  modules: ModuleDef[];
}

export interface UserProfile {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

export interface LoginResult {
  access: string;
  refresh: string;
  user: UserProfile;
}

export interface RegisterPayload {
  username: string;
  email: string;
  password: string;
  /** Согласие на обработку персональных данных (152-ФЗ, ТЗ п.7.3). */
  consent_pdn: boolean;
}

/**
 * Режим сервера. Нужен экрану входа: в self-hosted регистрация закрыта,
 * и вкладка «Регистрация» вела бы в 403 после заполнения формы.
 */
export interface PlatformConfig {
  mode: 'cloud' | 'self-hosted';
  registrationOpen: boolean;
  billingEnabled: boolean;
}

/** Тариф из шкалы (ТЗ п.17.1). null в лимите — без ограничения. */
export interface PlanOption {
  code: string;
  title: string;
  price: number;
  max_projects: number | null;
  max_pages: number | null;
  max_records: number | null;
  /** Кредиты помощника в месяц. null — без ограничения. */
  ai_credits: number | null;
  own_domain: boolean;
  cdn_priority: boolean;
  onedc_integration: boolean;
}

/** Занято и предел. null в limit — тариф не ограничивает. */
export interface PlanQuota {
  used: number;
  limit: number | null;
}

/**
 * Тариф, квоты и первые шаги.
 *
 * Использование приходит вместе с тарифом: два запроса на один экран
 * разошлись бы, если между ними успели создать проект.
 */
export interface SubscriptionInfo {
  plan: PlanOption;
  pending_plan: string;
  available: Record<string, boolean>;
  /** Сценарии с названиями: подписи не дублируются в интерфейсе. */
  scenarios: { code: number; title: string; available: boolean }[];
  plans: PlanOption[];
  usage: {
    projects: PlanQuota;
    pages: PlanQuota;
    records: PlanQuota;
    /** Кредиты ИИ за текущий месяц: счёт по владельцу проекта. */
    ai: PlanQuota;
  };
  publications: { published: number };
  billing_enabled: boolean;
}

/**
 * Проекты пользователя.
 *
 * Раньше идентификатор был зашит в редактор, и он открывал первый
 * найденный проект. Теперь проектом управляет список: он создаётся,
 * переименовывается и удаляется явно, а редактор получает готовый
 * идентификатор. Иначе удалённый проект открывался бы снова, а чужой
 * мог бы попасть в редактор по остаточному состоянию.
 */
export const api = {
  /** Проекты, доступные текущему пользователю. */
  listProjects: () => request<Project[]>('/projects/'),

  getProject: (id: string) => request<Project>(`/projects/${id}/`),

  /**
   * Сохранение с проверкой версии (ТЗ п.3.2).
   *
   * expectedVersion — та версия, которую редактор видел. Сервер
   * отвечает 409, если документ изменили с другой вкладки: молча
   * перезаписать чужую работу нельзя. Конфликт приходит отдельным
   * типом, чтобы показать предупреждение, а не «ошибку сети».
   */
  saveProject: (id: string, name: string, tree: unknown, expectedVersion?: number) =>
    request<Project>(`/projects/${id}/`, {
      method: 'PUT',
      body: JSON.stringify({
        name,
        tree,
        ...(expectedVersion === undefined ? {} : { expectedVersion }),
      }),
    }),

  /**
   * Сохранение брендбука.
   *
   * PATCH, а не PUT: ProjectSerializer на PUT требует name и tree, и
   * правка одного фирменного цвета перезаписывала бы документ целиком.
   * Частичное сохранение не создаёт версию: брендбук — оформление, а не
   * содержимое, и история версий должна оставаться историей правок.
   */
  saveBrand: (id: string, brand: ProjectBrand) =>
    request<Project>(`/projects/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ brand }),
    }),

  /**
   * Страницы проекта.
   *
   * Главная сюда не входит: её дерево приходит в getProject. Так
   * старые проекты и клиенты продолжают работать без миграции данных.
   */
  createPage: (projectId: string, title: string, slug?: string, tree?: unknown) =>
    request<ProjectPage>(`/projects/${projectId}/pages/`, {
      method: 'POST',
      body: JSON.stringify({
        title,
        ...(slug ? { slug } : {}),
        // Дерево передаётся при создании из шаблона: сервер проверяет
        // его теми же правилами, что и обычное сохранение.
        ...(tree === undefined ? {} : { tree }),
      }),
    }),

  getPage: (projectId: string, pageId: string) =>
    request<ProjectPage>(`/projects/${projectId}/pages/${pageId}/`),

  savePage: (
    projectId: string,
    pageId: string,
    tree: unknown,
    expectedVersion?: number,
  ) =>
    request<ProjectPage>(`/projects/${projectId}/pages/${pageId}/`, {
      method: 'PUT',
      body: JSON.stringify({
        tree,
        ...(expectedVersion === undefined ? {} : { expectedVersion }),
      }),
    }),

  deletePage: (projectId: string, pageId: string) =>
    request<void>(`/projects/${projectId}/pages/${pageId}/`, {
      method: 'DELETE',
    }),

  /** История версий документа. */
  versions: (id: string) =>
    request<{ version: number; versions: DocumentVersionRow[] }>(`/projects/${id}/versions/`),

  /** Ручная отметка: «запомнить состояние перед редизайном». */
  createVersion: (id: string, label: string) =>
    request<DocumentVersionRow>(`/projects/${id}/versions/`, {
      method: 'POST',
      body: JSON.stringify({ label }),
    }),

  /**
   * Адрес архива. Ссылка, а не тело ответа: файл может весить
   * десятки мегабайт, и держать его в памяти вкладки незачем —
   * браузер сохранит его сам по заголовку Content-Disposition.
   */
  exportUrl: (id: string, version?: number) => {
    const query = version === undefined ? '' : '?version=' + version;
    return `${BASE}/projects/${id}/export/${query}`;
  },

  /** Вернуть проект к версии. История при этом не переписывается. */
  restoreVersion: (id: string, number: number) =>
    request<DocumentVersionRow>(`/projects/${id}/versions/${number}/restore/`, { method: 'POST' }),

  createProject: (name: string, tree?: unknown) =>
    request<Project>('/projects/', {
      method: 'POST',
      body: JSON.stringify(tree === undefined ? { name } : { name, tree }),
    }),

  /** Переименование. Дерево не передаётся намеренно: PATCH меняет одно поле. */
  renameProject: (id: string, name: string) =>
    request<Project>(`/projects/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),

  deleteProject: (id: string) =>
    request<void>(`/projects/${id}/`, { method: 'DELETE' }),

  /** Права текущего пользователя в проекте. */
  members: (id: string) =>
    request<{ role: string; username: string }[]>(`/projects/${id}/members/`),

  /**
   * Вход по логину или email. Возвращает профиль вместе с токенами,
   * чтобы экран входа не делал второй запрос за данными пользователя.
   */
  async login(login: string, password: string): Promise<LoginResult> {
    const result = await request<LoginResult>('/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ login, password }),
    });
    setTokens(result.access, result.refresh);
    return result;
  },

  /** Регистрация. Токены не выдаются: подтверждение email — этап 8. */
  register(payload: RegisterPayload): Promise<UserProfile> {
    return request<UserProfile>('/auth/register/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** Профиль по сохранённому access-токену. */
  me: () => request<UserProfile>('/auth/me/'),

  /**
   * Выход. Refresh отзывается на сервере, access истекает сам через
   * 15 минут — отозвать выданный токен нельзя.
   */
  async logout(): Promise<void> {
    const refresh = getRefreshToken();
    try {
      if (refresh) {
        await request('/auth/logout/', {
          method: 'POST',
          body: JSON.stringify({ refresh }),
        });
      }
    } finally {
      // Локальные токены убираются даже при сетевой ошибке: оставить их
      // значит показать пользователю «вы вошли», когда сервер уже нет.
      clearTokens();
    }
  },

  /**
   * Каталог модулей. Без stage отдаётся весь реестр (65 модулей);
   * с stage — только доступные на этом этапе выпуска.
   */
  getModules: (stage?: number) =>
    request<ModuleCatalog>(`/modules/${stage === undefined ? '' : `?stage=${stage}`}`),

  /** Режим сервера. Публичный: экран входа ещё не имеет токена. */
  config: () => request<PlatformConfig>('/config/'),

  /** Тариф, квоты и доступные сценарии текущего пользователя. */
  subscription: () => request<SubscriptionInfo>('/billing/subscription/'),

  /** Смена тарифа. В self-hosted сервер откажет: тарифов там нет. */
  changePlan: (plan: string) =>
    request<{ plan: PlanOption; effective: string; note: string }>(
      '/billing/subscription/change/',
      { method: 'POST', body: JSON.stringify({ plan }) },
    ),

  health: () => request<{ status: string }>('/health/'),
};
