/**
 * Публикация и экспорт: клиент Control Plane.
 *
 * Все пять сценариев ТЗ п.16 сходятся здесь, и различаются они только
 * тем, что делает пользователь: нажать «опубликовать», скачать архив
 * или выложить на свой хостинг. Само решение платформы — это адрес
 * сервера и тело запроса; интерфейсу не нужно знать, чем отличается
 * публикация от деплоя на уровне протокола.
 *
 * Архивы не идут через `request`: файл может весить десятки мегабайт,
 * и возвращать его в память вкладки незачем — браузер сохранит его
 * сам по заголовку Content-Disposition. Поэтому здесь адреса.
 */

import { BASE, request } from './apiClient';

/** Состояние публикации (ТЗ п.16.3). */
export interface SiteStatus {
  slug: string;
  url: string;
  state: 'none' | 'published' | 'withdrawn';
  published: boolean;
  active: boolean;
  publishedAt: string | null;
  withdrawnAt: string | null;
  currentVersion: { number: number; size: number; files: number } | null;
  versions: { number: number; size: number; files: number }[];
  requests: number;
  lastRequestAt: string | null;
  backups: number;
}

/** Резервная копия публикации: одна строка в списке отката. */
export interface BackupItem {
  id: string;
  version: number;
  size: number;
  createdAt: string;
  /**
   * Копию можно восстановить. Бывает false, если каталог удалён с
   * диска: кнопка тогда не показывается, а не обещает пустое
   * действие.
   */
  restorable: boolean;
}

/** Профиль доступа к серверу (ТЗ п.16.5). */
export interface HostingProfile {
  id: string;
  name: string;
  kind: 'fs' | 'ftp';
  host: string;
  port: number;
  username: string;
  rootPath: string;
  runtimePath: string;
  siteUrl: string;
  hasSecret: boolean;
  secretEncrypted: boolean;
}

/** Отчёт о деплое. */
export interface DeployResult {
  ok: boolean;
  uploaded: string[];
  removed: string[];
  runtime: { url: string | null; ok: boolean; warnings: string[] };
  site: { url: string | null; ok: boolean; warnings: string[] };
  warnings: string[];
}

/**
 * Событие проекта: что собрали, опубликовали или выложили.
 *
 * Хранится на сервере, поэтому остаётся после закрытия вкладки. Это не
 * журнал аудита: здесь важен результат операции, а не только автор.
 */
export interface ProjectEvent {
  id: string;
  kind: 'build' | 'publish' | 'withdraw' | 'backup' | 'restore' | 'deploy';
  kindLabel: string;
  status: 'ok' | 'failed' | 'info';
  message: string;
  actor: string | null;
  createdAt: string;
}

/** Подключённый бот и привязка чата для уведомлений. */
export interface TelegramBotInfo {
  id: string;
  name: string;
  botUsername: string;
  botId: number | null;
  projectId: string;
  hasToken: boolean;
  menuConfigured: boolean;
  menuConfiguredAt: string | null;
  notifyChatId: number | null;
  notifyChatTitle: string;
  notifyEnabled: boolean;
  miniAppUrl: string;
  startAppLink: string;
  /** Только в ответе на привязку: ушло ли подтверждение. */
  notified?: boolean;
}

export const publishingApi = {
  /** Текущее состояние публикации. */
  status: (projectId: string) =>
    request<SiteStatus>(`/projects/${projectId}/site/`),

  /**
   * Публикация. `version` без значения публикует последнюю
   * сохранённую версию, а не текущее дерево: опубликованный сайт
   * должен соответствовать версии, иначе его нечем откатить.
   */
  publish: (projectId: string, version?: number) =>
    request<SiteStatus>(`/projects/${projectId}/site/`, {
      method: 'POST',
      body: JSON.stringify(version === undefined ? {} : { version }),
    }),

  /** Отзыв публикации: сайт отвечает 410, а не 404. */
  withdraw: (projectId: string) =>
    request<SiteStatus>(`/projects/${projectId}/site/withdraw/`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  /** Резервная копия опубликованной версии. */
  backup: (projectId: string) =>
    request<{ number: number; size: number; createdAt: string }>(
      `/projects/${projectId}/site/backup/`,
      { method: 'POST', body: JSON.stringify({}) },
    ),

  /**
   * Список копий, из которых можно восстановиться.
   *
   * Отдельный запрос, а не поле в состоянии публикации: список
   * растёт, а состояние читается при каждом входе на экран, и
   * десятки копий в нём мешали бы видеть, что сейчас с сайтом.
   */
  backups: (projectId: string) =>
    request<{ backups: BackupItem[] }>(`/projects/${projectId}/site/backups/`),

  /**
   * Возврат публикации к состоянию копии.
   *
   * Копия становится текущей версией: это откат, а не «новая
   * публикация поверх», иначе номер версии в истории перестал бы
   * соответствовать содержимому.
   */
  restoreBackup: (projectId: string, backupId: string) =>
    request<SiteStatus>(`/projects/${projectId}/site/backups/${backupId}/restore/`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  /**
   * Лента событий проекта.
   *
   * Отдельный запрос, а не поле в состоянии публикации: события
   * появляются и от деплоя, у которого своего состояния нет.
   */
  events: (projectId: string) =>
    request<{ events: ProjectEvent[] }>(`/projects/${projectId}/events/`),

  /** Боты проекта: через них уходят уведомления и открывается Mini App. */
  telegramBots: (projectId: string) =>
    request<{ bots: TelegramBotInfo[] }>(`/projects/${projectId}/telegram-bot/`),

  createTelegramBot: (
    projectId: string,
    bot: { name: string; botUsername: string; token: string },
  ) =>
    request<TelegramBotInfo>(`/projects/${projectId}/telegram-bot/`, {
      method: 'POST',
      body: JSON.stringify(bot),
    }),

  /** Настраивает кнопку меню: бот открывает Mini App проекта. */
  configureTelegramMenu: (projectId: string, botId: string) =>
    request<TelegramBotInfo>(
      `/projects/${projectId}/telegram-bot/${botId}/menu/`,
      { method: 'POST', body: JSON.stringify({}) },
    ),

  /**
   * Привязка чата для уведомлений.
   *
   * chat_id не передаётся: сервер читает, откуда бот получил последнее
   * сообщение. Поэтому перед привязкой владелец пишет боту /start.
   */
  bindTelegramChat: (projectId: string, botId: string) =>
    request<TelegramBotInfo>(
      `/projects/${projectId}/telegram-bot/${botId}/chat/`,
      { method: 'POST', body: JSON.stringify({}) },
    ),

  unbindTelegramChat: (projectId: string, botId: string) =>
    request<TelegramBotInfo>(
      `/projects/${projectId}/telegram-bot/${botId}/chat/`,
      { method: 'DELETE' },
    ),

  /**
 * Профили доступа к серверам заказчика.
 *
 * Ответ — массив, а не объект с полем: так его отдаёт Control Plane,
 * и клиент не должен придумывать обёртку, которой нет. Экран всё
 * равно проверяет `Array.isArray`: на тарифе без доступа приходит
 * отказ, и падать на этом не должен весь экран.
 */
profiles: (projectId: string) =>
  request<HostingProfile[]>(`/projects/${projectId}/hosting/`),

  /**
   * Добавление профиля. Пустой секрет не проходит: без него сервер
   * нечем открывать, а профиль без пароля бесполезен и только мешает.
   */
  createProfile: (
    projectId: string,
    profile: {
      name: string;
      kind: 'fs' | 'ftp';
      host: string;
      port: number;
      username: string;
      secret: string;
      rootPath: string;
      siteUrl: string;
    },
  ) =>
    request<HostingProfile>(`/projects/${projectId}/hosting/`, {
      method: 'POST',
      body: JSON.stringify(profile),
    }),

  deleteProfile: (projectId: string, profileId: string) =>
    request<void>(`/projects/${projectId}/hosting/${profileId}/`, {
      method: 'DELETE',
    }),

  /** Выкладка на хостинг заказчика (ТЗ п.16.5). */
  deploy: (projectId: string, profileId: string, version?: number) =>
    request<DeployResult>(`/projects/${projectId}/deploy/`, {
      method: 'POST',
      body: JSON.stringify({ profileId, ...(version === undefined ? {} : { version }) }),
    }),

  /**
   * Адреса архивов. Скачивание идёт браузером напрямую, поэтому здесь
   * нет запроса: файл может быть большим, и держать его в памяти
   * вкладки незачем.
   */
  exportUrl: (projectId: string, options: { version?: number; pwa?: boolean } = {}) => {
    const query: string[] = [];
    if (options.version !== undefined) query.push('version=' + options.version);
    if (options.pwa) query.push('pwa=1');
    return `${BASE}/projects/${projectId}/export/` +
      (query.length ? '?' + query.join('&') : '');
  },

  /** JSON-бэкап проекта (ТЗ п.16.7). */
  configUrl: (projectId: string) => `${BASE}/projects/${projectId}/config/`,
};