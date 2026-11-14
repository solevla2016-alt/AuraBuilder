/**
 * Экран публикации и экспорта (ТЗ п.16, сценарии 1–5).
 *
 * Пять сценариев на одном экране, потому что для человека это одно
 * действие — «показать сайт людям», а различаются они только тем, куда
 * сайт попадёт: на адрес платформы, в архив у него на диск, на его
 * сервер или в приложение на телефоне.
 *
 * Отказ по тарифу приходит кодом 402 и показывается словами, а не
 * «ошибкой»: человек должен понять, что делать, а не гадать, что
 * сломалось. Текст отказа присылает сервер вместе с минимальным
 * тарифом и его ценой.
 */

import { useCallback, useEffect, useState } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import {
  publishingApi,
  type DeployResult,
  type BackupItem,
  type HostingProfile,
  type ProjectEvent,
  type ScheduledPublication,
  type SiteStatus,
  type TelegramBotInfo,
} from './publishing';

type Props = {
  projectId: string;
  projectName: string;
  onBack: () => void;
};

type Notice = { kind: 'ok' | 'bad'; text: string };

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message || `Ошибка ${error.status}`;
  }
  return error instanceof Error ? error.message : 'Не получилось. Попробуйте ещё раз.';
}

const EMPTY_FORM = {
  name: '',
  kind: 'ftp' as 'fs' | 'ftp',
  host: '',
  port: 21,
  username: '',
  secret: '',
  rootPath: '',
  siteUrl: '',
};

const EMPTY_BOT = { name: '', botUsername: '', token: '' };

/** Значение для `datetime-local`: через час, в местном времени. */
function nextHour(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  const pad = (value: number) => String(value).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

export function PublishScreen({ projectId, projectName, onBack }: Props) {
  const [status, setStatus] = useState<SiteStatus | null>(null);
  const [profiles, setProfiles] = useState<HostingProfile[]>([]);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [deploy, setDeploy] = useState<DeployResult | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [bots, setBots] = useState<TelegramBotInfo[]>([]);
  const [botForm, setBotForm] = useState(EMPTY_BOT);
  const [showBotForm, setShowBotForm] = useState(false);
  const [scheduleAt, setScheduleAt] = useState(nextHour);

  const load = useCallback(async () => {
    try {
      const [site, hosting, copies, feed, telegram] = await Promise.all([
        publishingApi.status(projectId),
        // Профили могут быть недоступны на тарифе: отсутствие списка
        // не должно мешать публикации и выгрузке.
        publishingApi.profiles(projectId).catch(() => [] as HostingProfile[]),
        // Список копий — тоже необязательный: без него публикация
        // работает, пропадает только откат.
        publishingApi
          .backups(projectId)
          .then((body) => (Array.isArray(body.backups) ? body.backups : []))
          .catch(() => [] as BackupItem[]),
        // Лента событий и боты вспомогательные: их отсутствие не должно
        // скрывать состояние публикации и кнопки действий.
        publishingApi
          .events(projectId)
          .then((body) => (Array.isArray(body.events) ? body.events : []))
          .catch(() => [] as ProjectEvent[]),
        publishingApi
          .telegramBots(projectId)
          .then((body) => (Array.isArray(body.bots) ? body.bots : []))
          .catch(() => [] as TelegramBotInfo[]),
      ]);
      setStatus(site);
      setBackups(copies);
      setEvents(feed);
      setBots(telegram);
      // Ответ — массив; проверка здесь, потому что один неверный
      // элемент иначе уронил бы весь экран целиком.
      setProfiles(Array.isArray(hosting) ? hosting : []);
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = useCallback(
    async (key: string, action: () => Promise<Notice>) => {
      setBusy(key);
      setNotice(null);
      try {
        setNotice(await action());
        await load();
      } catch (e) {
        setNotice({ kind: 'bad', text: explain(e) });
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  const active = status?.active === true;
  const published = status?.published === true;

  const publish = () =>
    run('publish', async () => {
      const site = await publishingApi.publish(projectId);
      return { kind: 'ok', text: `Сайт опубликован: ${site.url}` };
    });

  const withdraw = () =>
    run('withdraw', async () => {
      await publishingApi.withdraw(projectId);
      return {
        kind: 'ok',
        text: 'Публикация отозвана. Сайт отвечает 410 — он был и был отозван. Вернуть можно одним нажатием.',
      };
    });

  const backup = () =>
    run('backup', async () => {
      const result = await publishingApi.backup(projectId);
      return {
        kind: 'ok',
        text: `Копия №${result.number} сделана (${Math.max(1, Math.round(result.size / 1024))} КБ).`,
      };
    });

  /**
   * Отложенная публикация.
   *
   * Браузер присылает местное время без зоны, сервер — ISO с зоной.
   * Проверка «в будущем» есть и здесь, и на сервере: первая нужна,
   * чтобы человек сразу увидел опечатку, вторая — потому что клиенту
   * доверять нельзя.
   */
  const schedule = () =>
    run('schedule', async () => {
      const when = new Date(scheduleAt);
      if (!scheduleAt || Number.isNaN(when.getTime())) {
        return { kind: 'bad', text: 'Укажите дату и время публикации.' };
      }
      if (when.getTime() <= Date.now()) {
        return { kind: 'bad', text: 'Время публикации должно быть в будущем.' };
      }
      await publishingApi.schedule(projectId, when.toISOString());
      return {
        kind: 'ok',
        text: `Версия собрана и выйдет ${when.toLocaleString('ru-RU')}.`,
      };
    });

  const cancelSchedule = (item: ScheduledPublication) =>
    run(`schedule-${item.id}`, async () => {
      await publishingApi.cancelSchedule(projectId, item.id);
      return {
        kind: 'ok',
        text: `Публикация версии ${item.version} отменена.`,
      };
    });

  /**
   * Откат к копии.
   *
   * Подтверждение обязательно: копия становится текущей версией, и
   * посетитель сразу видит её содержимое. Одно нажатие без вопроса
   * означало бы, что человек уводит сайт назад случайно — а заметит
   * об этом только посетитель.
   */
  const restore = (item: BackupItem) => {
    if (!window.confirm(
      `Вернуть сайт к копии версии ${item.version}?`
      + ' Текущая версия останется в истории, но посетители увидят копию.',
    )) {
      return;
    }
    void run(`restore-${item.id}`, async () => {
      await publishingApi.restoreBackup(projectId, item.id);
      return {
        kind: 'ok',
        text: `Сайт возвращён к копии версии ${item.version}.`,
      };
    });
  };

  const addProfile = () =>
    run('profile', async () => {
      const created = await publishingApi.createProfile(projectId, {
        ...form,
        port: Number(form.port) || 21,
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      return {
        kind: 'ok',
        text: `Профиль «${created.name}» добавлен. Пароль хранится зашифрованным и больше не показывается.`,
      };
    });

  const removeProfile = (profile: HostingProfile) =>
    run('profile', async () => {
      await publishingApi.deleteProfile(projectId, profile.id);
      return { kind: 'ok', text: `Профиль «${profile.name}» удалён.` };
    });

  const runDeploy = (profile: HostingProfile) =>
    run('deploy', async () => {
      const result = await publishingApi.deploy(projectId, profile.id);
      setDeploy(result);
      const failed = !result.site.ok || !result.runtime.ok;
      return {
        kind: failed ? 'bad' : 'ok',
        text: failed
          ? 'Файлы загружены, но проверка не прошла — отчёт ниже.'
          : `Загружено файлов: ${result.uploaded.length}.`,
      } as Notice;
    });

  const connectBot = () =>
    run('bot-create', async () => {
      const bot = await publishingApi.createTelegramBot(projectId, botForm);
      setBotForm(EMPTY_BOT);
      setShowBotForm(false);
      return {
        kind: 'ok',
        text:
          `Бот @${bot.botUsername} подключён. Откройте его в Telegram, ` +
          'отправьте /start и нажмите «Привязать чат».',
      };
    });

  const bindChat = (bot: TelegramBotInfo) =>
    run(`bind-${bot.id}`, async () => {
      const result = await publishingApi.bindTelegramChat(projectId, bot.id);
      return {
        kind: 'ok',
        text: result.notified === false
          ? 'Чат привязан, но подтверждение не дошло: Telegram мог быть недоступен. Следующие события всё равно уйдут в этот чат.'
          : `Уведомления включены: ${result.notifyChatTitle || result.notifyChatId}.`,
      };
    });

  const unbindChat = (bot: TelegramBotInfo) =>
    run(`unbind-${bot.id}`, async () => {
      await publishingApi.unbindTelegramChat(projectId, bot.id);
      return { kind: 'ok', text: 'Уведомления в этот чат отключены.' };
    });

  const configureMenu = (bot: TelegramBotInfo) =>
    run(`menu-${bot.id}`, async () => {
      await publishingApi.configureTelegramMenu(projectId, bot.id);
      return { kind: 'ok', text: 'Кнопка меню настроена: бот открывает сайт проекта.' };
    });

  const eventMark = (event: ProjectEvent) =>
    event.status === 'failed' ? '⚠️ ' : event.status === 'ok' ? '✓ ' : '· ';

  return (
    <main className="data vers">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Публикация: {projectName}</h1>
      </header>

      {notice ? (
        <p
          className={notice.kind === 'bad' ? 'data__error' : 'vers__ok'}
          role={notice.kind === 'bad' ? 'alert' : 'status'}
        >
          {notice.text}
        </p>
      ) : null}

      <section className="data__panel" data-screen="publish-events">
        <h2 className="data__panel-title">Последние события</h2>
        <p className="props__note">
          Что уже произошло с проектом. Лента остаётся после закрытия вкладки:
          по ней видно, чем закончилась последняя сборка или публикация.
        </p>
        {events.length === 0 ? (
          <p className="props__note">Пока ничего не происходило.</p>
        ) : (
          <ul className="vers__backup-list">
            {events.map((event) => (
              <li key={event.id} className="vers__backup">
                <span className="vers__backup-text">
                  {eventMark(event)}
                  <strong>{event.kindLabel}</strong> ·{' '}
                  {new Date(event.createdAt).toLocaleString('ru-RU')}
                  <br />
                  {event.message}
                  {event.actor ? ` · ${event.actor}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="data__panel" data-screen="publish-site">
        <h2 className="data__panel-title">1. Публикация на платформе</h2>
        <p className="props__note">
          Сайт получает адрес и открыт посетителям. Публикуется сохранённая версия, а
          не текущий черновик: так опубликованное можно откатить.
        </p>
        {status?.currentVersion ? (
          <p className="props__note">
            Опубликована версия {status.currentVersion.number} · обращений:{' '}
            {status.requests}
            {status.backups ? ` · копий: ${status.backups}` : ''}
          </p>
        ) : null}
        {active && status ? (
          <p>
            <a href={status.url} target="_blank" rel="noreferrer">
              {status.url}
            </a>
          </p>
        ) : null}
        <div className="vers__mark-row">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void publish()}
            disabled={busy !== null}
          >
            {busy === 'publish' ? 'Публикуем…' : active ? 'Опубликовать заново' : 'Опубликовать'}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => void withdraw()}
            disabled={!published || busy !== null}
          >
            Отозвать
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => void backup()}
            disabled={!published || busy !== null}
          >
            Сделать копию
          </button>
        </div>
        {published && !active ? (
          <p className="props__note">Публикация отозвана: сайт отвечает 410.</p>
        ) : null}

        {backups.length > 0 ? (
          <div className="vers__backups">
            <h3 className="vers__backups-title">Вернуться к копии</h3>
            <ul className="vers__backup-list">
              {backups.map((item) => (
                <li key={item.id} className="vers__backup">
                  <span className="vers__backup-text">
                    Версия {item.version} ·{' '}
                    {new Date(item.createdAt).toLocaleString('ru-RU')}
                  </span>
                  {item.restorable ? (
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => restore(item)}
                      disabled={busy !== null}
                    >
                      {busy === `restore-${item.id}` ? 'Возвращаем…' : 'Вернуть'}
                    </button>
                  ) : (
                    // Кнопка не показывается: обещание отката, который
                    // невозможен, хуже его отсутствия.
                    <span className="props__note">копия удалена с диска</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="vers__backups" data-screen="publish-schedule">
          <h3 className="vers__backups-title">Отложенная публикация</h3>
          <p className="props__note">
            Версия собирается сейчас, а сайт переключается на неё в указанное
            время. До этого посетители видят то, что опубликовано сейчас.
            Отзыв публикации отменяет запланированное.
          </p>
          <div className="vers__mark-row">
            <input
              type="datetime-local"
              className="prop__input"
              value={scheduleAt}
              onChange={(e) => setScheduleAt(e.target.value)}
              aria-label="Дата и время публикации"
              disabled={busy !== null}
            />
            <button
              type="button"
              className="btn"
              onClick={() => void schedule()}
              disabled={busy !== null}
            >
              {busy === 'schedule' ? 'Планируем…' : 'Запланировать'}
            </button>
          </div>
          {(status?.scheduled ?? []).length > 0 ? (
            <ul className="vers__backup-list">
              {(status?.scheduled ?? []).map((item) => (
                <li key={item.id} className="vers__backup">
                  <span className="vers__backup-text">
                    Версия {item.version} ·{' '}
                    {new Date(item.at).toLocaleString('ru-RU')}
                  </span>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => void cancelSchedule(item)}
                    disabled={busy !== null}
                  >
                    {busy === `schedule-${item.id}` ? 'Отменяем…' : 'Отменить'}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="props__note">Запланированных публикаций нет.</p>
          )}
        </div>
      </section>

      <section className="data__panel" data-screen="publish-export">
        <h2 className="data__panel-title">2. Выгрузка в статику</h2>
        <p className="props__note">
          Архив со всем сайтом. Папку можно положить на любой хостинг — он ничего не
          знает о платформе.
        </p>
        <div className="vers__mark-row">
          <a className="btn" href={publishingApi.exportUrl(projectId)}>
            Скачать архив
          </a>
        </div>
      </section>

      <section className="data__panel" data-screen="publish-deploy">
        <h2 className="data__panel-title">3. One-click deploy на ваш хостинг</h2>
        <p className="props__note">
          Загрузка по FTP или в папку на диске. Пароль хранится зашифрованным и больше
          не показывается.
        </p>
        {profiles.map((profile) => (
          <div key={profile.id} className="vers__mark-row">
            <span className="prop__label">
              <strong>{profile.name}</strong> ·{' '}
              {profile.kind === 'ftp' ? `${profile.host}:${profile.port}` : profile.rootPath}
              {profile.hasSecret ? '' : ' · без пароля'}
            </span>
            <button
              type="button"
              className="btn"
              onClick={() => void runDeploy(profile)}
              disabled={busy !== null}
            >
              {busy === 'deploy' ? 'Выкладываем…' : 'Выложить'}
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void removeProfile(profile)}
              disabled={busy !== null}
            >
              Удалить
            </button>
          </div>
        ))}
        {showForm ? (
          <div className="form">
            <label className="prop__label">
              Название
              <input
                className="prop__input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </label>
            <label className="prop__label">
              Способ
              <select
                className="prop__input"
                value={form.kind}
                onChange={(e) =>
                  setForm({ ...form, kind: e.target.value as 'fs' | 'ftp' })
                }
              >
                <option value="ftp">FTP</option>
                <option value="fs">Папка на диске</option>
              </select>
            </label>
            {form.kind === 'ftp' ? (
              <>
                <label className="prop__label">
                  Хост
                  <input
                    className="prop__input"
                    value={form.host}
                    onChange={(e) => setForm({ ...form, host: e.target.value })}
                  />
                </label>
                <label className="prop__label">
                  Логин
                  <input
                    className="prop__input"
                    value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                  />
                </label>
                <label className="prop__label">
                  Пароль или ключ
                  <input
                    className="prop__input"
                    type="password"
                    value={form.secret}
                    onChange={(e) => setForm({ ...form, secret: e.target.value })}
                  />
                </label>
              </>
            ) : null}
            <label className="prop__label">
              Папка на сервере
              <input
                className="prop__input"
                value={form.rootPath}
                onChange={(e) => setForm({ ...form, rootPath: e.target.value })}
              />
            </label>
            <label className="prop__label">
              Адрес сайта для проверки
              <input
                className="prop__input"
                value={form.siteUrl}
                onChange={(e) => setForm({ ...form, siteUrl: e.target.value })}
              />
            </label>
            <div className="vers__mark-row">
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void addProfile()}
                disabled={busy !== null}
              >
                {busy === 'profile' ? 'Сохраняем…' : 'Сохранить профиль'}
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => setShowForm(false)}>
                Отмена
              </button>
            </div>
          </div>
        ) : (
          <div className="vers__mark-row">
            <button type="button" className="btn" onClick={() => setShowForm(true)}>
              Добавить профиль
            </button>
          </div>
        )}
        {deploy ? (
          <div className="props__note">
            <p>Загружено: {deploy.uploaded.join(', ') || '—'}</p>
            {deploy.site.warnings.map((w) => (
              <p key={'site' + w}>Сайт: {w}</p>
            ))}
            {deploy.runtime.warnings.map((w) => (
              <p key={'rt' + w}>Рантайм: {w}</p>
            ))}
          </div>
        ) : null}
      </section>

      <section className="data__panel" data-screen="publish-pwa">
        <h2 className="data__panel-title">4. Приложение на телефоне (PWA)</h2>
        <p className="props__note">
          Тот же сайт с манифестом и работой без сети: его можно установить на главный
          экран телефона.
        </p>
        <div className="vers__mark-row">
          <a className="btn" href={publishingApi.exportUrl(projectId, { pwa: true })}>
            Скачать как приложение
          </a>
        </div>
      </section>

      <section className="data__panel" data-screen="publish-backup">
        <h2 className="data__panel-title">5. Бэкап проекта (JSON)</h2>
        <p className="props__note">
          Дерево, версии, узлы данных и стили. Доступен на любом тарифе: это
          техническая гарантия сохранности данных.
        </p>
        <div className="vers__mark-row">
          <a className="btn" href={publishingApi.configUrl(projectId)}>
            Скачать бэкап
          </a>
        </div>
      </section>

      <section className="data__panel" data-screen="publish-telegram">
        <h2 className="data__panel-title">6. Уведомления в Telegram</h2>
        <p className="props__note">
          События проекта приходят в чат, который владелец привяжет к боту.
          Откройте бота в Telegram, отправьте ему <code>/start</code> и нажмите
          «Привязать чат»: вводить числовой идентификатор не нужно.
        </p>
        {bots.length === 0 ? (
          <p className="props__note">
            Бот ещё не подключён. Подключение требует тарифа Pro и токена от
            @BotFather.
          </p>
        ) : (
          bots.map((bot) => (
            <div key={bot.id} className="vers__mark-row">
              <span className="prop__label">
                <strong>@{bot.botUsername}</strong> ·{' '}
                {bot.notifyEnabled
                  ? `чат: ${bot.notifyChatTitle || bot.notifyChatId}`
                  : 'чат не привязан'}
              </span>
              <button
                type="button"
                className="btn"
                onClick={() => void bindChat(bot)}
                disabled={busy !== null || !bot.hasToken}
              >
                {busy === `bind-${bot.id}` ? 'Привязываем…' : 'Привязать чат'}
              </button>
              {bot.notifyEnabled ? (
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => void unbindChat(bot)}
                  disabled={busy !== null}
                >
                  Отключить
                </button>
              ) : null}
              {bot.hasToken && !bot.menuConfigured ? (
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => void configureMenu(bot)}
                  disabled={busy !== null}
                >
                  {busy === `menu-${bot.id}` ? 'Настраиваем…' : 'Настроить меню'}
                </button>
              ) : null}
            </div>
          ))
        )}
        {showBotForm ? (
          <div className="form">
            <label className="prop__label">
              Название
              <input
                className="prop__input"
                value={botForm.name}
                onChange={(e) => setBotForm({ ...botForm, name: e.target.value })}
              />
            </label>
            <label className="prop__label">
              Логин бота
              <input
                className="prop__input"
                value={botForm.botUsername}
                placeholder="shop_bot"
                onChange={(e) =>
                  setBotForm({ ...botForm, botUsername: e.target.value })
                }
              />
            </label>
            <label className="prop__label">
              Токен от @BotFather
              <input
                className="prop__input"
                type="password"
                value={botForm.token}
                onChange={(e) => setBotForm({ ...botForm, token: e.target.value })}
              />
            </label>
            <div className="vers__mark-row">
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void connectBot()}
                disabled={busy !== null}
              >
                {busy === 'bot-create' ? 'Проверяем…' : 'Подключить'}
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setShowBotForm(false)}
              >
                Отмена
              </button>
            </div>
          </div>
        ) : (
          <div className="vers__mark-row">
            <button
              type="button"
              className="btn"
              onClick={() => setShowBotForm(true)}
            >
              Подключить бота
            </button>
          </div>
        )}
      </section>
    </main>
  );
}