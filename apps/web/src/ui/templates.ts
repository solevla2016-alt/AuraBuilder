/**
 * Шаблоны страниц и блоков: клиент Control Plane.
 *
 * Шаблон — снимок внутри проекта, а не ссылка на страницу: правка
 * страницы после сохранения шаблона его не меняет. Поэтому клиенту
 * важно различать список (подписи) и содержимое (дерево): дерево
 * тянется только в момент применения.
 */

import { request } from './apiClient';
import type { Block, PageTree } from './project';

export type TemplateKind = 'page' | 'block';

/** Строка списка: без дерева, оно может быть большим. */
export interface TemplateSummary {
  id: string;
  kind: TemplateKind;
  name: string;
  /** Откуда снят шаблон: заголовок страницы или подпись блока. */
  title: string;
  module: string;
  blocks: number;
  createdAt: string;
}

/** Шаблон вместе с содержимым. */
export interface TemplateDetail extends TemplateSummary {
  /** Для страницы — всё дерево, для блока — один блок верхнего уровня. */
  tree: PageTree | Block;
  meta: {
    title?: string;
    slug?: string;
    seoTitle?: string;
    seoDescription?: string;
    module?: string;
    label?: string;
  };
}

export interface TemplateCreatePayload {
  name: string;
  kind: TemplateKind;
  /** Пусто — главная страница проекта. */
  page?: string;
  /** Нужен только для блока. */
  block?: string;
}

export const templatesApi = {
  list: (projectId: string) =>
    request<{ templates: TemplateSummary[]; limit: number }>(
      `/projects/${projectId}/templates/`,
    ),

  create: (projectId: string, payload: TemplateCreatePayload) =>
    request<TemplateDetail>(`/projects/${projectId}/templates/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  get: (projectId: string, templateId: string) =>
    request<TemplateDetail>(`/projects/${projectId}/templates/${templateId}/`),

  remove: (projectId: string, templateId: string) =>
    request<void>(`/projects/${projectId}/templates/${templateId}/`, {
      method: 'DELETE',
    }),
};
