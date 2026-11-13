/**
 * Экран аналитики проекта.
 *
 * Владельцу сайта нужны три ответа: сколько людей пришло, откуда они и
 * сколько из них оставили заявку. Поэтому экран начинается с этих
 * чисел, а таблицы источников и страниц идут ниже — они объясняют
 * цифры, но не заменяют их.
 *
 * Данные читаются с сервера при каждом переключении периода. Кеша на
 * клиенте нет намеренно: отчёт маленький, а устаревшая статистика
 * хуже, чем короткая загрузка.
 */

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from './apiClient';
import { analyticsApi, type AnalyticsReport, type Period } from './analytics';
import { Icon } from './icons';

type Props = {
  projectId: string;
  projectName: string;
  onBack: () => void;
};

const PERIODS: { value: Period; label: string }[] = [
  { value: 7, label: '7 дней' },
  { value: 30, label: '30 дней' },
  { value: 90, label: '90 дней' },
];

/** Дата в коротком виде: в графике и таблицах важен день, не год. */
function dayLabel(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
}

function fullDay(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  });
}

function percent(share: number): string {
  return `${Math.round(share * 100)}%`;
}

function plural(value: number, one: string, few: string, many: string): string {
  const tens = value % 100;
  const units = value % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (units === 1) return one;
  if (units >= 2 && units <= 4) return few;
  return many;
}

export function AnalyticsScreen({ projectId, projectName, onBack }: Props) {
  const [days, setDays] = useState<Period>(7);
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await analyticsApi.report(projectId, days));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить статистику.');
    } finally {
      setLoading(false);
    }
  }, [projectId, days]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxViews = report
    ? Math.max(1, ...report.series.map((point) => point.views))
    : 1;

  return (
    <main className="data vers">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Аналитика: {projectName}</h1>
      </header>

      <div className="vers__mark-row" role="group" aria-label="Период отчёта">
        <div className="top-bar__group">
          {PERIODS.map((period) => (
            <button
              key={period.value}
              type="button"
              className={period.value === days ? 'btn btn--primary' : 'btn'}
              aria-pressed={period.value === days}
              onClick={() => setDays(period.value)}
            >
              {period.label}
            </button>
          ))}
        </div>
        {report?.site ? (
          <a
            className="btn btn--ghost"
            href={report.site.url}
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="external" size={16} />
            Открыть сайт
          </a>
        ) : null}
      </div>

      {error ? (
        <p className="data__error" role="alert">
          {error}
        </p>
      ) : null}

      {loading && report === null ? (
        <p className="props__note">Считаем…</p>
      ) : null}

      {report && report.site === null ? (
        <section className="data__panel">
          <h2 className="data__panel-title">Сайт ещё не опубликован</h2>
          <p className="props__note">
            Статистика появляется после первой публикации: считать просмотры
            нечего, пока сайт не открыт посетителям. Заявки с формы начнут
            приходить туда же.
          </p>
        </section>
      ) : null}

      {report && report.site !== null ? (
        <>
          <section className="data__panel" data-screen="analytics-totals">
            <h2 className="data__panel-title">За {days} дней</h2>
            <div className="stat-grid">
              <div className="stat-card">
                <span className="stat-card__value">{report.totals.views}</span>
                <span className="stat-card__label">
                  {plural(report.totals.views, 'просмотр', 'просмотра', 'просмотров')}
                </span>
              </div>
              <div className="stat-card">
                <span className="stat-card__value">{report.totals.submissions}</span>
                <span className="stat-card__label">заявок</span>
              </div>
              <div className="stat-card">
                <span className="stat-card__value">
                  {report.totals.conversion.toLocaleString('ru-RU')}%
                </span>
                <span className="stat-card__label">конверсия формы</span>
              </div>
            </div>
            <p className="props__note">
              Конверсия — доля заявок от просмотров страниц. Считаются только
              сайты, которые раздаёт платформа: копия на чужом хостинге о
              статистике ничего не сообщает.
            </p>
          </section>

          <section className="data__panel" data-screen="analytics-chart">
            <h2 className="data__panel-title">Просмотры по дням</h2>
            <div
              className="stat-chart"
              role="img"
              aria-label={`Просмотры за ${days} дней`}
            >
              {report.series.map((point) => (
                <div
                  key={point.day}
                  className="stat-chart__col"
                  title={`${fullDay(point.day)}: ${point.views} просм., ${point.submissions} заявок`}
                >
                  <div
                    className={
                      point.views ? 'stat-chart__bar' : 'stat-chart__bar is-empty'
                    }
                    style={{
                      height: `${Math.round((point.views / maxViews) * 100)}%`,
                    }}
                  />
                  <span className="stat-chart__day">
                    {days === 7 ? dayLabel(point.day) : ''}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section className="data__panel" data-screen="analytics-sources">
            <h2 className="data__panel-title">Источники переходов</h2>
            {report.sources.length === 0 ? (
              <p className="props__note">Пока нет данных.</p>
            ) : (
              <table className="stat-table">
                <thead>
                  <tr>
                    <th scope="col">Источник</th>
                    <th scope="col">Просмотры</th>
                    <th scope="col">Доля</th>
                  </tr>
                </thead>
                <tbody>
                  {report.sources.map((row) => (
                    <tr key={row.source}>
                      <td>{row.source}</td>
                      <td>{row.views}</td>
                      <td>{percent(row.share)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="props__note">
              «search» и «social» — поисковики и соцсети, «direct» — переход
              без реферера, «internal» — переход внутри сайта. Домены вне
              этих групп показываются как есть.
            </p>
          </section>

          <section className="data__panel" data-screen="analytics-pages">
            <h2 className="data__panel-title">Страницы</h2>
            {report.pages.length === 0 ? (
              <p className="props__note">Пока нет данных.</p>
            ) : (
              <table className="stat-table">
                <thead>
                  <tr>
                    <th scope="col">Страница</th>
                    <th scope="col">Просмотры</th>
                    <th scope="col">Доля</th>
                  </tr>
                </thead>
                <tbody>
                  {report.pages.map((row) => (
                    <tr key={row.path}>
                      <td>{row.path}</td>
                      <td>{row.views}</td>
                      <td>{percent(row.share)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="data__panel" data-screen="analytics-submissions">
            <h2 className="data__panel-title">Последние заявки</h2>
            <p className="props__note">
              Поля формы — так, как их ввёл посетитель. Заявки хранятся, пока
              существует сайт: это данные, за которыми к вам пришли.
            </p>
            {report.submissions.length === 0 ? (
              <p className="props__note">Заявок за период не было.</p>
            ) : (
              <ul className="stat-submissions">
                {report.submissions.map((row) => (
                  <li key={row.id} className="stat-submission">
                    <div className="stat-submission__top">
                      <strong>{row.page}</strong>
                      <span className="stat-submission__meta">
                        {new Date(row.createdAt).toLocaleString('ru-RU')}
                        {row.source ? ` · ${row.source}` : ''}
                      </span>
                    </div>
                    <dl className="stat-submission__fields">
                      {Object.entries(row.fields).map(([name, value]) => (
                        <div key={name}>
                          <dt>{name}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
