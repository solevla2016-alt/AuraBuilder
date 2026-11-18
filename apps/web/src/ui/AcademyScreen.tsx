/**
 * Академия: короткие уроки по сборке и ведению сайта.
 *
 * Уроки идут от первого проекта к аналитике: человек, который только
 * открыл редактор, не должен искать «с чего начать» в документации.
 * Прогресс отмечается вручную — платформа не угадывает, понял ли
 * человек шаг, а хранит его собственное решение.
 *
 * Экран общий для всех ролей и не привязан к проекту: Viewer тоже
 * учится, прежде чем оставлять замечания.
 */

import { useCallback, useEffect, useState } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import { academyApi, type AcademySummary } from './academy';

type Props = {
  onBack: () => void;
};

type Notice = { kind: 'ok' | 'bad'; text: string };

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message || `Ошибка ${error.status}`;
  }
  return error instanceof Error ? error.message : 'Не получилось. Попробуйте ещё раз.';
}

/** «1 минута», «3 минуты», «5 минут». */
function minutesLabel(count: number): string {
  const tail = count % 100;
  const last = count % 10;
  if (tail >= 11 && tail <= 14) return `${count} минут`;
  if (last === 1) return `${count} минута`;
  if (last >= 2 && last <= 4) return `${count} минуты`;
  return `${count} минут`;
}

export function AcademyScreen({ onBack }: Props) {
  const [summary, setSummary] = useState<AcademySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const load = useCallback(async () => {
    const fresh = await academyApi.list();
    setSummary(fresh);
  }, []);

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

  const toggle = async (lessonId: string, completed: boolean) => {
    if (busy !== null) return;
    setBusy(lessonId);
    setNotice(null);
    try {
      if (completed) {
        await academyApi.uncomplete(lessonId);
      } else {
        await academyApi.complete(lessonId);
      }
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const total = summary?.total ?? 0;
  const done = summary?.completed ?? 0;
  const percent = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <main className="data academy">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В кабинет</span>
        </button>
        <h1 className="data__title">Академия</h1>
      </header>

      {notice ? (
        <p
          className={notice.kind === 'bad' ? 'data__error' : 'vers__ok'}
          role={notice.kind === 'bad' ? 'alert' : 'status'}
        >
          {notice.text}
        </p>
      ) : null}

      <section className="data__panel" data-screen="academy-progress">
        <div className="academy__head">
          <div>
            <h2 className="data__panel-title">Ваш прогресс</h2>
            <p className="props__note">
              Уроки короткие: по одному действию за шаг. Отметку можно
              снять и вернуться позже — прогресс принадлежит вам, а не
              проекту.
            </p>
          </div>
          <span className="academy__count">
            {done} из {total}
          </span>
        </div>
        <div
          className="academy__bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={done}
          aria-label="Пройдено уроков"
        >
          <span className="academy__bar-fill" style={{ width: `${percent}%` }} />
        </div>
      </section>

      {loading ? (
        <p className="data__hint">Загружаем уроки…</p>
      ) : summary === null ? (
        <p className="data__hint">Уроки не загрузились. Обновите страницу.</p>
      ) : (
        summary.tracks.map((track) => (
          <section
            key={track.id}
            className="data__panel"
            data-screen={`academy-${track.id}`}
          >
            <div className="academy__head">
              <h2 className="data__panel-title">{track.title}</h2>
              <span className="academy__count">
                {track.completed} из {track.total}
              </span>
            </div>

            <ul className="academy__list">
              {track.lessons.map((lesson) => (
                <li
                  key={lesson.id}
                  className={
                    lesson.completed
                      ? 'academy__lesson is-done'
                      : 'academy__lesson'
                  }
                >
                  <div className="academy__lesson-head">
                    <div>
                      <b>{lesson.title}</b>
                      <span className="academy__meta">
                        {minutesLabel(lesson.minutes)}
                        {lesson.completed ? ' · пройден' : ''}
                      </span>
                    </div>
                    <span
                      className={
                        lesson.completed
                          ? 'review__badge review__badge--approved'
                          : 'review__badge review__badge--draft'
                      }
                    >
                      {lesson.completed ? 'Пройден' : 'Не пройден'}
                    </span>
                  </div>
                  <p className="academy__summary">{lesson.summary}</p>

                  <details className="academy__steps">
                    <summary>Шаги урока</summary>
                    <ol>
                      {lesson.steps.map((step, index) => (
                        <li key={index}>{step}</li>
                      ))}
                    </ol>
                  </details>

                  <div className="tpl__actions">
                    <button
                      type="button"
                      className={lesson.completed ? 'btn btn--ghost' : 'btn'}
                      onClick={() => void toggle(lesson.id, lesson.completed)}
                      disabled={busy !== null}
                    >
                      {busy === lesson.id
                        ? 'Сохраняем…'
                        : lesson.completed
                          ? 'Снять отметку'
                          : 'Отметить пройденным'}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </main>
  );
}
