/**
 * SDK AuraBuilder: клиент публичного API и проверка вебхуков.
 *
 * Пакет не зависит от платформы: ни Django, ни React, ни сети при
 * импорте. Поэтому его можно положить в чужой сервис, который только
 * принимает вебхуки и никогда не видит наш редактор (ТЗ п.16.4).
 */

export {
  AuraClient,
  type AuraClientOptions,
  type ExportOptions,
  type FetchLike,
  type ListOptions,
} from './client.js';
export { AuraApiError } from './errors.js';
export type {
  ApiDescription,
  ApiEndpoint,
  AuthUser,
  BlockTree,
  ExportedArchive,
  LoginResult,
  PageDetail,
  PageList,
  Paginated,
  PaginationMeta,
  ProjectBrand,
  ProjectDetail,
  ProjectRole,
  ProjectSummary,
  TokenPair,
  VersionList,
  VersionSummary,
} from './types.js';
export {
  WEBHOOK_DELIVERY_HEADER,
  WEBHOOK_EVENT_HEADER,
  WEBHOOK_EVENT_KINDS,
  WEBHOOK_EVENT_LABELS,
  WEBHOOK_SIGNATURE_HEADER,
  WebhookPayloadError,
  WebhookSignatureError,
  parseWebhook,
  verifySignature,
  verifyWebhook,
  type VerifySignatureOptions,
  type WebhookBody,
  type WebhookEvent,
  type WebhookEventKind,
  type WebhookEventStatus,
  type WebhookPayload,
  type WebhookProject,
} from './webhooks.js';
