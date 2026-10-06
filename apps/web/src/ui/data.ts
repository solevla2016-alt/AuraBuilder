/**
 * Клиент узлов данных.
 *
 * Отдельный файл, а не часть api.ts: у узлов данных своя модель
 * (источник, поля, записи) и свои адреса, и смешивать их с проектами
 * значило бы держать в одном месте два разных словаря.
 *
 * Имена полей — camelCase, как в остальном клиенте (apps/web/src/ui/
 * project.ts, data.ts на сервере).
 */

import { request } from './apiClient';

export interface DataField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'boolean' | 'date' | 'image' | 'link';
  required: boolean;
}

export interface DataSource {
  id: string;
  name: string;
  key: string;
  description: string;
  fields: DataField[];
  recordCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface DataRecord {
  id: string;
  externalId: string;
  data: Record<string, string | number | boolean | null>;
  position: number;
  createdAt: string;
  updatedAt: string;
}

export interface RecordPage {
  total: number;
  records: DataRecord[];
}

export interface RecordPayload {
  data: Record<string, string | number | boolean | null>;
  externalId?: string;
}

export const FIELD_TYPES: { code: DataField['type']; label: string }[] = [
  { code: 'text', label: 'Текст' },
  { code: 'number', label: 'Число' },
  { code: 'boolean', label: 'Да или нет' },
  { code: 'date', label: 'Дата' },
  { code: 'image', label: 'Изображение' },
  { code: 'link', label: 'Ссылка' },
];

export const dataApi = {
  listSources: (projectId: string) => request<DataSource[]>(`/projects/${projectId}/data/`),

  createSource: (
    projectId: string,
    body: { name: string; key?: string; description?: string; fields: DataField[] },
  ) => request<DataSource>(`/projects/${projectId}/data/`, {
    method: 'POST',
    body: JSON.stringify(body),
  }),

  updateSource: (
    sourceId: string,
    body: Partial<Pick<DataSource, 'name' | 'description' | 'fields'>>,
  ) => request<DataSource>(`/data/${sourceId}/`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  }),

  deleteSource: (sourceId: string) => request<void>(`/data/${sourceId}/`, { method: 'DELETE' }),

  listRecords: (sourceId: string, limit = 100) =>
    request<RecordPage>(`/data/${sourceId}/records/?limit=${limit}`),

  createRecord: (sourceId: string, body: RecordPayload) =>
    request<DataRecord>(`/data/${sourceId}/records/`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  updateRecord: (recordId: string, body: Partial<RecordPayload>) =>
    request<DataRecord>(`/data/records/${recordId}/`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  deleteRecord: (recordId: string) =>
    request<void>(`/data/records/${recordId}/`, { method: 'DELETE' }),
};

/** Текст значения ячейки: даты и числа показываем как есть, булевы — словами. */
export function cellText(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  return String(value);
}

/** Ключ поля из названия на русском: используется при создании источника. */
export function fieldKeyFrom(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-zа-я0-9]+/gi, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40);
}
