/**
 * Аналитика опубликованного сайта: клиент Control Plane.
 *
 * Отдельно от `publishing.ts`: публикация меняет сайт, аналитика
 * только читает. Общий модуль смешал бы действия с отчётом, и экран
 * публикации тянул бы типы статистики, которая ему не нужна.
 */

import { request } from './apiClient';

/** Периоды, которые предлагает экран. Сервер принимает те же три. */
export type Period = 7 | 30 | 90;

export interface AnalyticsTotals {
  views: number;
  submissions: number;
  /** Процент заявок от просмотров, уже умноженный на 100. */
  conversion: number;
}

export interface AnalyticsPoint {
  day: string;
  views: number;
  submissions: number;
}

export interface AnalyticsRow {
  views: number;
  /** Доля от всех просмотров периода: 0…1. */
  share: number;
}

export interface AnalyticsSource extends AnalyticsRow {
  source: string;
}

export interface AnalyticsPage extends AnalyticsRow {
  path: string;
}

export interface SubmissionRow {
  id: string;
  page: string;
  source: string;
  createdAt: string;
  fields: Record<string, string>;
}

export interface AnalyticsReport {
  days: number;
  site: {
    slug: string;
    url: string;
    published: boolean;
    currentVersion: number | null;
  } | null;
  totals: AnalyticsTotals;
  series: AnalyticsPoint[];
  sources: AnalyticsSource[];
  pages: AnalyticsPage[];
  submissions: SubmissionRow[];
}

export const analyticsApi = {
  report: (projectId: string, days: Period) =>
    request<AnalyticsReport>(`/projects/${projectId}/analytics/?days=${days}`),
};
