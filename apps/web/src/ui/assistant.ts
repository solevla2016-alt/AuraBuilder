/**
 * Клиент ИИ-помощника.
 *
 * Отдельный файл, как review.ts и data.ts: у помощника свой словарь
 * (кредиты, действия, история) и свои адреса под проектом. Держать его
 * в api.ts значило бы смешивать проекты с расходом кредитов.
 *
 * Провайдер выбирает сервер. Интерфейс лишь показывает, какой именно:
 * человек должен знать, уходит ли описание во внешнюю модель.
 */

import { request } from './apiClient';

export interface AssistantProvider {
  code: string;
  title: string;
  /** true — описание уходит во внешний сервис. */
  external: boolean;
  /** false — выбран YandexGPT без ключа: запуск вернёт 502. */
  ready: boolean;
  detail: string;
}

/** Остаток кредитов. null в limit — без ограничения (Business/self-hosted). */
export interface AssistantCredits {
  used: number;
  limit: number | null;
  remaining: number | null;
  /** ГГГГ-ММ: календарный месяц, к которому относится остаток. */
  period: string;
  /** Первый день следующего месяца — дата обнуления. */
  resets_at: string;
}

export interface AssistantAction {
  code: string;
  title: string;
  description: string;
  cost: number;
  placeholder: string;
  needs_description: boolean;
  available: boolean;
}

/** Один запрос в журнале расхода. Промпт и результат сюда не входят. */
export interface AssistantRequest {
  id: string;
  action: string;
  action_title: string;
  credits: number;
  provider: string;
  actor: string;
  created_at: string;
}

export interface AssistantInfo {
  project: { id: string; name: string };
  provider: AssistantProvider;
  credits: AssistantCredits;
  actions: AssistantAction[];
  recent: AssistantRequest[];
  billing_enabled: boolean;
  plan: string;
  can_edit: boolean;
  description_limits: { min: number; max: number };
}

/** Элемент ответа. Поля зависят от действия: секции или поля данных. */
export interface AssistantItem {
  title?: string;
  label?: string;
  key?: string;
  module?: string;
  type?: string;
  required?: boolean;
  detail?: string;
}

export interface AssistantResult {
  summary: string;
  items: AssistantItem[];
  provider: string;
  tokens: number;
}

export interface AssistantRun {
  result: AssistantResult;
  credits: AssistantCredits;
  request: AssistantRequest;
}

export const assistantApi = {
  status: (projectId: string) =>
    request<AssistantInfo>(`/projects/${projectId}/assistant/`),

  run: (projectId: string, action: string, description: string) =>
    request<AssistantRun>(`/projects/${projectId}/assistant/run/`, {
      method: 'POST',
      body: JSON.stringify({
        action,
        description,
      }),
    }),
};
