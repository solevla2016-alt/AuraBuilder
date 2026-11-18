/**
 * Академия: клиент уроков и прогресса.
 *
 * Уроки приходят с сервера одним списком: содержание живёт в коде
 * платформы, а прогресс — у пользователя. Поэтому клиент не хранит
 * тексты у себя и не пытается считать пройденное по проекту.
 */

import { request } from './apiClient';

export interface AcademyLesson {
  id: string;
  track: string;
  title: string;
  summary: string;
  minutes: number;
  steps: string[];
  completed: boolean;
  completedAt: string | null;
}

export interface AcademyTrack {
  id: string;
  title: string;
  lessons: AcademyLesson[];
  completed: number;
  total: number;
}

export interface AcademySummary {
  tracks: AcademyTrack[];
  completed: number;
  total: number;
}

export const academyApi = {
  list: () => request<AcademySummary>('/academy/'),

  complete: (lessonId: string) =>
    request<{ lessonId: string; completed: boolean }>(
      `/academy/${encodeURIComponent(lessonId)}/complete/`,
      { method: 'POST' },
    ),

  uncomplete: (lessonId: string) =>
    request<void>(`/academy/${encodeURIComponent(lessonId)}/complete/`, {
      method: 'DELETE',
    }),
};
