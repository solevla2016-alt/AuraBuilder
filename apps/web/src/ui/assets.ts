/**
 * Клиент медиатеки проекта.
 *
 * Отдельный файл по той же причине, что и data.ts: у файлов проекта
 * своя модель и свои адреса, а мешать их с проектами и источниками
 * данных в одном словаре — значит держать в одном месте два разных
 * словаря.
 *
 * Имена полей — camelCase, как в остальном клиенте.
 */

import { request } from './apiClient';

export interface Asset {
  id: string;
  name: string;
  originalName: string;
  contentType: string;
  size: number;
  url: string;
  createdAt: string;
}

export const assetsApi = {
  list: (projectId: string) =>
    request<{ assets: Asset[] }>(`/projects/${projectId}/assets/`).then(
      (body) => body.assets,
    ),

  /**
   * Загрузка одного файла.
   *
   * Файлы отправляются по одному, а не пачкой: ответ сервера содержит
   * понятную причину отказа по каждому файлу («только изображения»,
   * «исполняемый код в SVG»), и при пачке непонятно было бы, кому из
   * файлов её адресовать.
   */
  upload: (projectId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<Asset>(`/projects/${projectId}/assets/`, {
      method: 'POST',
      body: form,
    });
  },

  remove: (projectId: string, assetId: string) =>
    request<void>(`/projects/${projectId}/assets/${assetId}/`, {
      method: 'DELETE',
    }),
};

/** «2,3 МБ» вместо «2097152»: размер должен читаться, а не считаться. */
export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} МБ`;
}