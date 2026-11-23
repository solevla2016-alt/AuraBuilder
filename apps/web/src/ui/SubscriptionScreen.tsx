/**
 * Экран тарифа и квот.
 *
 * Зачем отдельный экран, а не строка в кабинете: лимит проекта — это
 * не справка, а причина, по которой следующий проект не создаётся.
 * Человеку нужно видеть, что именно кончилось, сколько осталось и
 * какой тариф это снимает, в одном месте.
 *
 * Оплата здесь не подключена сознательно: смена тарифа — решение
 * платформы, а платёжный провайдер появится отдельным этапом. Поэтому
 * экран не делает вид, что списывает деньги, и пишет об этом прямо.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  api,
  type PlanOption,
  type PlanQuota,
  type SubscriptionInfo,
} from './api';
import { Icon } from './icons';

export function SubscriptionScreen({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<SubscriptionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.subscription());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить тариф.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function choose(plan: PlanOption) {
    if (busy || !data || plan.code === data.plan.code) return;
    setBusy(true);
    setError(null);
    try {
      await api.changePlan(plan.code);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сменить тариф.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="dash">
      <header className="dash__top">
        <div className="dash__brand">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={onBack}
            aria-label="Вернуться к проектам"
          >
            <Icon name="back" />
          </button>
          <div>
            <span className="dash__title">Тариф и квоты</span>
            <p className="dash__user">Использование и доступные возможности</p>
          </div>
        </div>
      </header>

      <section className="billing">
        {error ? (
          <p className="dash__error" role="alert">
            {error}
          </p>
        ) : null}

        {data === null ? (
          <p className="dash__hint">Загружаем тариф…</p>
        ) : !data.billing_enabled ? (
          <section className="billing__panel">
            <h2>Тарифы отключены</h2>
            <p>
              Это self-hosted установка. Все возможности доступны без
              подписки, а технические лимиты задаёт администратор сервера.
            </p>
          </section>
        ) : (
          <>
            <section className="billing__panel billing__current">
              <div>
                <span className="billing__eyebrow">Текущий тариф</span>
                <h2>{data.plan.title}</h2>
                <p>
                  {data.plan.price === 0
                    ? 'Бесплатно'
                    : `${data.plan.price.toLocaleString('ru-RU')} ₽ в месяц`}
                  {data.publications.published > 0
                    ? ` · опубликовано сайтов: ${data.publications.published}`
                    : ' · опубликованных сайтов пока нет'}
                </p>
              </div>
              <div className="billing__scenarios" aria-label="Что доступно">
                {data.scenarios.map((scenario) => (
                  <span
                    key={scenario.code}
                    className={
                      scenario.available
                        ? 'billing__scenario is-on'
                        : 'billing__scenario is-off'
                    }
                  >
                    <Icon
                      name={scenario.available ? 'check' : 'close'}
                      size={13}
                    />
                    {scenario.title}
                  </span>
                ))}
              </div>
            </section>

            <section aria-labelledby="usage-title">
              <h2 id="usage-title" className="billing__heading">
                Использование
              </h2>
              <div className="billing__quotas">
                <QuotaMeter label="Проекты" quota={data.usage.projects} />
                <QuotaMeter label="Страницы" quota={data.usage.pages} />
                <QuotaMeter label="Записи в источниках" quota={data.usage.records} />
              </div>
            </section>

            <section aria-labelledby="plans-title">
              <h2 id="plans-title" className="billing__heading">
                Тарифы
              </h2>
              <div className="billing__plans">
                {data.plans.map((plan) => (
                  <article
                    key={plan.code}
                    className={
                      plan.code === data.plan.code
                        ? 'billing__plan is-current'
                        : 'billing__plan'
                    }
                  >
                    <header>
                      <h3>{plan.title}</h3>
                      <p className="billing__price">
                        {plan.price === 0
                          ? '0 ₽'
                          : `${plan.price.toLocaleString('ru-RU')} ₽`}
                        <span> / мес</span>
                      </p>
                    </header>
                    <ul className="billing__features">
                      {planFeatures(plan).map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                    <button
                      type="button"
                      className={
                        plan.code === data.plan.code
                          ? 'btn btn--ghost'
                          : 'btn btn--primary'
                      }
                      disabled={busy || plan.code === data.plan.code}
                      onClick={() => void choose(plan)}
                    >
                      {plan.code === data.plan.code ? 'Текущий' : 'Перейти'}
                    </button>
                  </article>
                ))}
              </div>
            </section>

            <p className="billing__note">
              Оплата подключается отдельным этапом. Сейчас смена тарифа
              действует сразу и не списывает средства; превышение лимита
              блокирует только новые проекты и публикации, уже
              опубликованные сайты продолжают работать.
            </p>
          </>
        )}
      </section>
    </main>
  );
}

/** Полоса «занято из предела». Без предела полосы нет: 100% врали бы. */
function QuotaMeter({ label, quota }: { label: string; quota: PlanQuota }) {
  const ratio =
    quota.limit === null || quota.limit === 0
      ? 0
      : Math.min(100, Math.round((quota.used / quota.limit) * 100));
  const state =
    quota.limit !== null && quota.used >= quota.limit
      ? ' is-full'
      : ratio >= 80
        ? ' is-near'
        : '';

  return (
    <article className={`billing__quota${state}`}>
      <header>
        <span>{label}</span>
        <b>
          {quota.used}
          {quota.limit === null ? ' · без ограничения' : ` из ${quota.limit}`}
        </b>
      </header>
      {quota.limit === null ? null : (
        <div
          className="billing__bar"
          role="progressbar"
          aria-label={label}
          aria-valuenow={quota.used}
          aria-valuemin={0}
          aria-valuemax={quota.limit}
        >
          <span style={{ width: `${ratio}%` }} />
        </div>
      )}
    </article>
  );
}

/** Что входит в тариф, словами. null — без ограничения. */
function planFeatures(plan: PlanOption): string[] {
  const lines = [
    plan.max_projects === null
      ? 'Проекты без ограничения'
      : `Проектов: ${plan.max_projects}`,
    plan.max_pages === null
      ? 'Страницы без ограничения'
      : `Страниц: ${plan.max_pages}`,
    plan.max_records === null
      ? 'Записи без ограничения'
      : `Записей: ${plan.max_records}`,
    plan.own_domain ? 'Свой домен' : 'Только адрес платформы',
  ];
  if (plan.cdn_priority) lines.push('Приоритет CDN');
  if (plan.onedc_integration) lines.push('Интеграция с 1С');
  return lines;
}
