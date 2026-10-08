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

import type { DocumentVersionRow, Project } from './project';
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

  health: () => request<{ status: string }>('/health/'),
};
