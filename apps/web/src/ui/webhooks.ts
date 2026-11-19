/**
 * Вебхуки: клиент подписок и журнала доставок.
 *
 * Секрет приходит в ответе, потому что его нужно сверить с приёмником.
 * Клиент не пытается его скрыть: человек, открывший этот экран, уже
 * управляет интеграциями проекта.
 */

import { request } from './apiClient';

export interface WebhookDelivery {
  id: string;
  event: string;
  status: 'ok' | 'failed';
  attempts: number;
  responseCode: number | null;
  error: string;
  createdAt: string;
  deliveredAt: string | null;
}

export interface WebhookEvent {
  id: string;
  label: string;
}

export interface Webhook {
  id: string;
  url: string;
  /** Пустой список — все события проекта. */
  events: string[];
  active: boolean;
  secret: string;
  createdAt: string;
  latest: WebhookDelivery | null;
  deliveries?: WebhookDelivery[];
}

export interface WebhookList {
  webhooks: Webhook[];
  events: WebhookEvent[];
  limit: number;
}

export interface WebhookPayload {
  url?: string;
  events?: string[];
  active?: boolean;
}

export const webhooksApi = {
  list: (projectId: string) =>
    request<WebhookList>(`/projects/${projectId}/webhooks/`),

  create: (projectId: string, payload: WebhookPayload) =>
    request<Webhook>(`/projects/${projectId}/webhooks/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  update: (projectId: string, webhookId: string, payload: WebhookPayload) =>
    request<Webhook>(`/projects/${projectId}/webhooks/${webhookId}/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  remove: (projectId: string, webhookId: string) =>
    request<void>(`/projects/${projectId}/webhooks/${webhookId}/`, {
      method: 'DELETE',
    }),

  rotate: (projectId: string, webhookId: string) =>
    request<Webhook>(
      `/projects/${projectId}/webhooks/${webhookId}/rotate/`,
      { method: 'POST' },
    ),

  retry: (projectId: string, webhookId: string, deliveryId: string) =>
    request<WebhookDelivery>(
      `/projects/${projectId}/webhooks/${webhookId}/deliveries/` +
        `${deliveryId}/retry/`,
      { method: 'POST' },
    ),
};
