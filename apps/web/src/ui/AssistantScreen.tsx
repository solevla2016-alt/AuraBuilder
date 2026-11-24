/**
 * ИИ-помощник проекта.
 *
 * Помощник предлагает структуру, а не меняет проект: страницы и поля
 * собирает человек. Это сознательное ограничение — автоматическая
 * вставка блоков в чужой холст без подтверждения ломала бы работу,
 * которую он уже сделал.
 *
 * Расход показан до нажатия кнопки (цена действия) и после (остаток и
 * журнал). «Понятный расход» — это когда можно ответить, куда ушли
 * кредиты, не открывая базу.
 */

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from './api';
import {
  assistantApi,
  type AssistantAction,
  type AssistantInfo,
  type AssistantItem,
  type AssistantResult,
} from './assistant';
import { Icon } from './icons';

const TYPE_LABELS: Record<string, string> = {
  text: 'текст',
  number: 'число',
  boolean: 'да/нет',
  date: 'дата',
  image: 'изображение',
  link: 'ссылка',
};

export function AssistantScreen({
  projectId,
  projectName,
  onBack,
  onOpenSubscription,
}: {
  projectId: string;
  projectName: string;
  onBack: () => void;
  /** Переход к тарифу, когда кредиты кончились. */
  onOpenSubscription: () => void;
}) {
  const [info, setInfo] = useState<AssistantInfo | null>(null);
  const [code, setCode] = useState('page_outline');
  const [description, setDescription] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AssistantResult | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await assistantApi.status(projectId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить помощника.');
      setInfo(null);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const action =
    info?.actions.find((item) => item.code === code) ?? info?.actions[0];
  const credits = info?.credits;
  const exhausted =
    credits !== undefined &&
    credits.limit !== null &&
    credits.remaining !== null &&
    credits.remaining <= 0;
  const canRun =
    info !== null &&
    action !== undefined &&
    info.can_edit &&
    info.provider.ready &&
    !running &&
    (credits?.limit === null ||
      (credits?.remaining !== null && (credits?.remaining ?? 0) >= action.cost)) &&
    (!action.needs_description ||
      description.trim().length >= info.description_limits.min);

  async function run() {
    if (!info || !action || !canRun) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const payload = await assistantApi.run(
        projectId,
        action.code,
        description,
      );
      setResult(payload.result);
      setInfo({
        ...info,
        credits: payload.credits,
        recent: [payload.request, ...info.recent].slice(0, 8),
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось получить ответ.');
      // Остаток мог измениться (402) — перечитываем, а не показываем
      // устаревшее число рядом с сообщением об отказе.
      void load();
    } finally {
      setRunning(false);
    }
  }

  function choose(next: AssistantAction) {
    setCode(next.code);
    setDescription('');
    setResult(null);
    setError(null);
  }

  return (
    <main className="dash">
      <header className="dash__top">
        <div className="dash__brand">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={onBack}
            aria-label="Вернуться в редактор"
          >
            <Icon name="back" />
          </button>
          <div>
            <span className="dash__title">ИИ-помощник</span>
            <p className="dash__user">{projectName}</p>
          </div>
        </div>
        {credits ? (
          <div className="assistant__balance" aria-label="Кредиты помощника">
            <b>
              {credits.remaining === null ? '∞' : credits.remaining}
            </b>
            <span>
              {credits.limit === null
                ? 'без ограничений'
                : `из ${credits.limit} в этом месяце`}
            </span>
          </div>
        ) : null}
      </header>

      <section className="assistant">
        {error ? (
          <p className="dash__error" role="alert">
            {error}
          </p>
        ) : null}

        {info === null ? (
          <p className="dash__hint">Загружаем помощника…</p>
        ) : (
          <>
            <section className="assistant__provider" aria-label="Провайдер">
              <span className={info.provider.external ? 'is-external' : ''}>
                {info.provider.title}
              </span>
              <p>{info.provider.detail}</p>
            </section>

            <div className="assistant__layout">
              <section className="assistant__ask" aria-labelledby="ask-title">
                <h2 id="ask-title">Что сделать</h2>
                <div className="assistant__actions" aria-label="Действие">
                  {info.actions.map((item) => (
                    <button
                      key={item.code}
                      type="button"
                      className={
                        item.code === action?.code
                          ? 'assistant__action is-current'
                          : 'assistant__action'
                      }
                      aria-pressed={item.code === action?.code}
                      onClick={() => choose(item)}
                    >
                      <b>{item.title}</b>
                      <span>{item.description}</span>
                      <em>{item.cost} {creditsWord(item.cost)}</em>
                    </button>
                  ))}
                </div>

                {action?.needs_description ? (
                  <label className="assistant__field">
                    <span>Описание</span>
                    <textarea
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      placeholder={action.placeholder}
                      maxLength={info.description_limits.max}
                      rows={4}
                    />
                    <small>
                      {description.trim().length < info.description_limits.min
                        ? `Ещё минимум ${info.description_limits.min - description.trim().length} символов.`
                        : 'Опишите задачу словами — помощник предложит структуру.'}
                    </small>
                  </label>
                ) : (
                  <p className="dash__hint">
                    Описание не нужно: помощник смотрит на состав проекта.
                  </p>
                )}

                <button
                  type="button"
                  className="btn btn--primary assistant__run"
                  disabled={!canRun}
                  onClick={() => void run()}
                >
                  <Icon name="sparkles" size={16} />
                  {running
                    ? 'Спрашиваем…'
                    : action
                      ? `Спросить · ${action.cost} ${creditsWord(action.cost)}`
                      : 'Спросить'}
                </button>

                {!info.can_edit ? (
                  <p className="dash__hint">
                    Запускать помощника может тот, кто меняет содержимое
                    проекта. Подсказки доступны на чтение.
                  </p>
                ) : null}
                {!info.provider.ready ? (
                  <p className="dash__error">
                    Провайдер выбран, но не настроен. Администратору сервера
                    нужно задать ключ или вернуть локальные подсказки.
                  </p>
                ) : null}
              </section>

              <section className="assistant__answer" aria-live="polite">
                {result ? (
                  <>
                    <header>
                      <span className="billing__eyebrow">Ответ</span>
                      <b>
                        {result.provider === 'yandex'
                          ? 'YandexGPT'
                          : 'Локальные правила'}
                      </b>
                    </header>
                    <p className="assistant__summary">{result.summary}</p>
                    <ol className="assistant__items">
                      {result.items.map((item, index) => (
                        <li key={`${item.key ?? item.title ?? item.label}-${index}`}>
                          <ItemHead item={item} />
                          {item.detail ? <p>{item.detail}</p> : null}
                        </li>
                      ))}
                    </ol>
                    <p className="dash__hint">
                      Это предложение, а не изменение проекта: модули и поля
                      добавляются вручную.
                    </p>
                  </>
                ) : (
                  <p className="assistant__empty">
                    Ответ появится здесь: сначала выберите действие и опишите
                    задачу.
                  </p>
                )}
              </section>
            </div>

            {exhausted ? (
              <section className="assistant__limit" role="status">
                <div>
                  <b>Кредиты на этот месяц закончились</b>
                  <p>
                    Остаток обнулится {formatDate(credits?.resets_at)}. Больше
                    кредитов даёт тариф выше.
                  </p>
                </div>
                {info.billing_enabled ? (
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={onOpenSubscription}
                  >
                    Сменить тариф
                  </button>
                ) : null}
              </section>
            ) : null}

            {info.recent.length > 0 ? (
              <section
                className="assistant__history"
                aria-labelledby="history-title"
              >
                <h2 id="history-title">Расход кредитов</h2>
                <ul>
                  {info.recent.map((item) => (
                    <li key={item.id}>
                      <span>{item.action_title}</span>
                      <span className="assistant__history-meta">
                        {item.actor ? `${item.actor} · ` : ''}
                        {formatWhen(item.created_at)}
                      </span>
                      <b>
                        −{item.credits} {creditsWord(item.credits)}
                      </b>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        )}
      </section>
    </main>
  );
}

function ItemHead({ item }: { item: AssistantItem }) {
  const title = item.title || item.label || item.key || 'Без названия';
  return (
    <div className="assistant__item-head">
      <b>{title}</b>
      {item.key && item.key !== title ? <code>{item.key}</code> : null}
      {item.module ? <code>{item.module}</code> : null}
      {item.type ? <span>{TYPE_LABELS[item.type] ?? item.type}</span> : null}
      {item.required ? (
        <span className="assistant__required">обязательное</span>
      ) : null}
    </div>
  );
}

/** «1 кредит / 2 кредита / 5 кредитов» — без склонения «кредит(ов)». */
function creditsWord(count: number): string {
  const last = count % 10;
  const lastTwo = count % 100;
  if (last === 1 && lastTwo !== 11) return 'кредит';
  if (last >= 2 && last <= 4 && (lastTwo < 10 || lastTwo >= 20)) {
    return 'кредита';
  }
  return 'кредитов';
}

function formatDate(value: string | undefined): string {
  if (!value) return 'в начале следующего месяца';
  return new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
  });
}

function formatWhen(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}
