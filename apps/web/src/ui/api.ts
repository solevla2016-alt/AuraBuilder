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

import type { Project } from './project';
import type { CategoryDef, ModuleDef } from './moduleRegistry';

const BASE = (import.meta.env['VITE_API_BASE'] as string | undefined) ?? '/api';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    // Текст ошибки с сервера полезнее «500»: он уже валидирован.
    let detail = `${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ответ не JSON — оставляем код
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ModuleCatalog {
  total: number;
  categories: CategoryDef[];
  modules: ModuleDef[];
}

export const api = {
  getProject: (id: string) => request<Project>(`/projects/${id}/`),

  saveProject: (id: string, name: string, tree: unknown) =>
    request<Project>(`/projects/${id}/`, {
      method: 'PUT',
      body: JSON.stringify({ name, tree }),
    }),

  createProject: (name: string, tree: unknown) =>
    request<Project>('/projects/', {
      method: 'POST',
      body: JSON.stringify({ name, tree }),
    }),

  /**
   * Каталог модулей. Без stage отдаётся весь реестр (65 модулей);
   * с stage — только доступные на этом этапе выпуска.
   */
  getModules: (stage?: number) =>
    request<ModuleCatalog>(`/modules/${stage === undefined ? '' : `?stage=${stage}`}`),

  health: () => request<{ status: string }>('/health/'),
};
