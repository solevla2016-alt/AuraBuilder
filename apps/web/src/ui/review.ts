/**
 * Ревью-режим: клиент Control Plane.
 *
 * Комментарии и статус согласования живут на платформе и в пакет не
 * попадают. Поэтому клиент читает их отдельным эндпоинтом, а не из
 * Project: иначе редактор таскал бы замечания при каждом сохранении.
 */

import { request } from './apiClient';
import type { ReviewStatus } from './project';

export interface ReviewPage {
  id: string;
  title: string;
  slug: string;
  status: ReviewStatus;
  approvedBy: string;
  approvedAt: string | null;
  openComments: number;
}

export interface ReviewSummary {
  status: ReviewStatus;
  approvedBy: string;
  approvedAt: string | null;
  /** Открытые замечания по проекту, включая главную страницу. */
  openComments: number;
  pages: ReviewPage[];
}

export interface ReviewComment {
  id: string;
  /** null — главная страница: её дерево лежит в Project.tree. */
  page: string | null;
  blockId: string;
  text: string;
  author: string;
  parent: string | null;
  resolved: boolean;
  resolvedBy: string;
  createdAt: string;
  resolvedAt: string | null;
}

export type ReviewAction = 'request' | 'approve' | 'changes';

export interface CommentPayload {
  text: string;
  /** Пусто — главная страница. */
  page?: string;
  blockId?: string;
  parent?: string;
}

export const reviewApi = {
  summary: (projectId: string) =>
    request<ReviewSummary>(`/projects/${projectId}/review/`),

  act: (projectId: string, action: ReviewAction, page?: string) =>
    request<ReviewSummary>(`/projects/${projectId}/review/`, {
      method: 'POST',
      body: JSON.stringify({ action, ...(page ? { page } : {}) }),
    }),

  comments: (projectId: string, page?: string) => {
    const suffix = page === undefined ? '' : `?page=${encodeURIComponent(page)}`;
    return request<{ comments: ReviewComment[] }>(
      `/projects/${projectId}/comments/${suffix}`,
    );
  },

  addComment: (projectId: string, payload: CommentPayload) =>
    request<ReviewComment>(`/projects/${projectId}/comments/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  resolve: (projectId: string, commentId: string, resolved: boolean) =>
    request<ReviewComment>(`/projects/${projectId}/comments/${commentId}/`, {
      method: 'PATCH',
      body: JSON.stringify({ resolved }),
    }),

  remove: (projectId: string, commentId: string) =>
    request<void>(`/projects/${projectId}/comments/${commentId}/`, {
      method: 'DELETE',
    }),
};
