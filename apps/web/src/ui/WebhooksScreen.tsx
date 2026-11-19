/**
 * Вебхуки: подписки проекта на его события.
 *
 * Экран отдельный, как у шаблонов и ревью: настройка интеграции — это
 * не правка страницы, и смешивать её с холстом значило бы искать адрес
 * приёмника среди свойств блока.
 *
 * Подпись показывается рядом с секретом не для красоты: без неё
 * приёмник не отличит наш запрос от чужого. Секрет видит только тот,
 * кому доступны интеграции.
 */

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import {
  webhooksApi,
  type Webhook,
  type WebhookDelivery,
  type WebhookEvent,
} from './webhooks';

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

function moment(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function eventsLabel(hook: Webhook, catalog: WebhookEvent[]): string {
  if (hook.events.length === 0) return 'Все события';
  const labels = new Map(catalog.map((item) => [item.id, item.label]));
  return hook.events
    .map((id) => labels.get(id) ?? id)
    .join(', ');
}

function deliveryLine(
  delivery: WebhookDelivery,
  catalog: WebhookEvent[],
): string {
  const labels = new Map(catalog.map((item) => [item.id, item.label]));
  const event = labels.get(delivery.event) ?? delivery.event;
  const tail =
    delivery.status === 'ok'
      ? `доставлено${delivery.responseCode ? ` · код ${delivery.responseCode}` : ''}`
      : `не доставлено${delivery.responseCode ? ` · код ${delivery.responseCode}` : ''}` +
        (delivery.error ? ` · ${delivery.error}` : '');
  return `${event} · ${moment(delivery.createdAt)} · ${tail}`;
}

export function WebhooksScreen({ projectId, projectName, onBack }: Props) {
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [limit, setLimit] = useState(5);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [url, setUrl] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const listing = await webhooksApi.list(projectId);
    setHooks(listing.webhooks);
    setEvents(listing.events);
    setLimit(listing.limit);
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void load()
      .catch((e) => {
        if (!cancelled) setNotice({ kind: 'bad', text: explain(e) });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const create = async (formEvent: FormEvent) => {
    formEvent.preventDefault();
    const clean = url.trim();
    if (!clean || busy !== null) return;
    setBusy('create');
    setNotice(null);
    try {
      await webhooksApi.create(projectId, { url: clean, events: selected });
      setUrl('');
      setSelected([]);
      setNotice({
        kind: 'ok',
        text: 'Вебхук добавлен. Сверьте секрет с настройками приёмника.',
      });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (hook: Webhook) => {
    if (busy !== null) return;
    setBusy(`toggle-${hook.id}`);
    setNotice(null);
    try {
      await webhooksApi.update(projectId, hook.id, { active: !hook.active });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const rotate = async (hook: Webhook) => {
    if (busy !== null) return;
    setBusy(`rotate-${hook.id}`);
    setNotice(null);
    try {
      await webhooksApi.rotate(projectId, hook.id);
      setNotice({
        kind: 'ok',
        text: 'Секрет обновлён. Старый больше не принимается — обновите приёмник.',
      });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const retry = async (hook: Webhook, delivery: WebhookDelivery) => {
    if (busy !== null) return;
    setBusy(`retry-${delivery.id}`);
    setNotice(null);
    try {
      const fresh = await webhooksApi.retry(projectId, hook.id, delivery.id);
      setNotice(
        fresh.status === 'ok'
          ? { kind: 'ok', text: 'Доставка прошла: приёмник принял событие.' }
          : {
              kind: 'bad',
              text: `Снова не доставлено${fresh.error ? `: ${fresh.error}` : '.'}`,
            },
      );
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const remove = async (hook: Webhook) => {
    if (busy !== null) return;
    // Удаление вместе с журналом необратимо: первый клик спрашивает.
    if (confirmingId !== hook.id) {
      setConfirmingId(hook.id);
      return;
    }
    setBusy(`delete-${hook.id}`);
    setNotice(null);
    try {
      await webhooksApi.remove(projectId, hook.id);
      setConfirmingId(null);
      setNotice({ kind: 'ok', text: 'Вебхук удалён.' });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const copySecret = (secret: string) => {
    void navigator.clipboard
      ?.writeText(secret)
      .then(() => setNotice({ kind: 'ok', text: 'Секрет скопирован.' }))
      .catch(() => setNotice({ kind: 'bad', text: 'Скопируйте секрет вручную.' }));
  };

  const toggleEvent = (id: string) => {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  };

  return (
    <main className="data tpl wh">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Вебхуки: {projectName}</h1>
      </header>

      {notice ? (
        <p
          className={notice.kind === 'bad' ? 'data__error' : 'vers__ok'}
          role={notice.kind === 'bad' ? 'alert' : 'status'}
        >
          {notice.text}
        </p>
      ) : null}

      <section className="data__panel" data-screen="webhooks-create">
        <h2 className="data__panel-title">Новая подписка</h2>
        <p className="props__note">
          Платформа пришлёт POST с событием проекта на ваш адрес. Тело
          подписано секретом: заголовок <code>X-Aura-Signature</code>,
          формат <code>sha256=&lt;hmac&gt;</code>. Без выбранных событий
          подписка получает все.
        </p>
        <form className="tpl__form" onSubmit={(e) => void create(e)}>
          <label className="prop">
            <span className="prop__label">Адрес приёмника</span>
            <input
              className="prop__input"
              value={url}
              maxLength={500}
              placeholder="https://example.com/hooks/aura"
              onChange={(e) => setUrl(e.target.value)}
              disabled={busy !== null}
            />
          </label>

          <fieldset className="prop wh__events">
            <legend className="prop__label">События</legend>
            {events.map((item) => (
              <label key={item.id} className="wh__check">
                <input
                  type="checkbox"
                  checked={selected.includes(item.id)}
                  onChange={() => toggleEvent(item.id)}
                  disabled={busy !== null}
                />
                <span>{item.label}</span>
              </label>
            ))}
            <span className="props__note">
              {selected.length === 0
                ? 'Ничего не выбрано — подписка на все события.'
                : `Выбрано: ${selected.length}.`}
            </span>
          </fieldset>

          <div className="data__actions tpl__submit">
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy !== null || !url.trim()}
            >
              {busy === 'create' ? 'Добавляем…' : 'Добавить вебхук'}
            </button>
            <span className="props__note">
              {hooks.length} из {limit}
            </span>
          </div>
        </form>
      </section>

      <section className="data__panel" data-screen="webhooks-list">
        <h2 className="data__panel-title">Подписки проекта</h2>
        {loading ? (
          <p className="data__hint">Загружаем вебхуки…</p>
        ) : hooks.length === 0 ? (
          <p className="props__note">
            Пока пусто. Добавьте адрес, если публикации и выкладки должны
            попадать в ваш сервис без ручной проверки.
          </p>
        ) : (
          <ul className="tpl__list">
            {hooks.map((hook) => {
              const deliveries = hook.deliveries ?? [];
              const last = hook.latest;
              return (
                <li key={hook.id} className="tpl__row wh__row">
                  <div className="tpl__text">
                    <div className="wh__head">
                      <b className="wh__url">{hook.url}</b>
                      <span
                        className={
                          hook.active
                            ? 'review__badge review__badge--approved'
                            : 'review__badge review__badge--draft'
                        }
                      >
                        {hook.active ? 'Включён' : 'Отключён'}
                      </span>
                    </div>
                    <span className="tpl__meta">
                      {eventsLabel(hook, events)}
                    </span>

                    <div className="wh__secret-row">
                      <span className="props__note">Секрет подписи</span>
                      <code className="wh__secret">{hook.secret}</code>
                      <button
                        type="button"
                        className="btn btn--ghost btn--small"
                        onClick={() => copySecret(hook.secret)}
                      >
                        Копировать
                      </button>
                    </div>

                    <p className="props__note">
                      {last === null
                        ? 'Доставок ещё не было: событий этого вида пока не случалось.'
                        : `Последняя доставка: ${deliveryLine(last, events)}.`}
                    </p>

                    {deliveries.length > 0 ? (
                      <details className="wh__history">
                        <summary>История доставок</summary>
                        <ul className="wh__deliveries">
                          {deliveries.map((delivery) => (
                            <li key={delivery.id} className="wh__delivery">
                              <span
                                className={
                                  delivery.status === 'ok'
                                    ? 'review__badge review__badge--approved'
                                    : 'review__badge review__badge--changes'
                                }
                              >
                                {delivery.status === 'ok'
                                  ? 'Доставлено'
                                  : 'Не доставлено'}
                              </span>
                              <span className="wh__delivery-text">
                                {deliveryLine(delivery, events)}
                                {delivery.attempts > 1
                                  ? ` · попыток: ${delivery.attempts}`
                                  : ''}
                              </span>
                              {delivery.status === 'failed' ? (
                                <button
                                  type="button"
                                  className="btn btn--ghost btn--small"
                                  onClick={() => void retry(hook, delivery)}
                                  disabled={busy !== null}
                                >
                                  {busy === `retry-${delivery.id}`
                                    ? 'Повторяем…'
                                    : 'Повторить'}
                                </button>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>

                  <div className="tpl__actions">
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => void rotate(hook)}
                      disabled={busy !== null}
                    >
                      {busy === `rotate-${hook.id}` ? 'Обновляем…' : 'Новый секрет'}
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => void toggle(hook)}
                      disabled={busy !== null}
                    >
                      {hook.active ? 'Отключить' : 'Включить'}
                    </button>
                    <button
                      type="button"
                      className={
                        confirmingId === hook.id
                          ? 'btn btn--danger'
                          : 'btn btn--ghost'
                      }
                      onClick={() => void remove(hook)}
                      disabled={busy !== null}
                    >
                      {busy === `delete-${hook.id}`
                        ? 'Удаляем…'
                        : confirmingId === hook.id
                          ? 'Точно удалить?'
                          : 'Удалить'}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </main>
  );
}
