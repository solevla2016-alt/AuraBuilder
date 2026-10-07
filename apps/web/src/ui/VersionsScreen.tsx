/**
 * Экран версий документа (ТЗ п.3.2).
 *
 * История нужна не «на всякий случай», а для конкретной беды:
 * правка сделана, оказалась неудачной, и вернуть нужно вчерашнее
 * состояние. Поэтому здесь важны две вещи: видно, кто и когда сохранял,
 * и восстановление не уничтожает текущую работу.
 *
 * Восстановление не переписывает историю — оно само становится
 * версией. Иначе «отменить восстановление» было бы нечем, а
 * сотрудник, восстановивший не то, исправлял бы это вручную.
 */

import { useCallback, useEffect, useState } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import { api } from './api';
import type { DocumentVersionRow } from './project';

type Props = {
  projectId: string;
  onBack: () => void;
};

function when(iso: string): string {
  // Дата приходит в ISO с часовым поясом сервера. Подпись делается
  // локально: пользователю нужна его местная дата, а не серверная.
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function VersionsScreen({ projectId, onBack }: Props) {
  const [rows, setRows] = useState<DocumentVersionRow[] | null>(null);
  const [current, setCurrent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState('');
  const [restored, setRestored] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api.versions(projectId);
      setRows(body.versions);
      setCurrent(body.version);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить версии.');
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function mark() {
    if (busy) return;
    setBusy(true);
    try {
      await api.createVersion(projectId, label.trim());
      setLabel('');
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить отметку.');
    } finally {
      setBusy(false);
    }
  }

  async function restore(row: DocumentVersionRow) {
    if (busy) return;
    setBusy(true);
    try {
      await api.restoreVersion(projectId, row.number);
      await load();
      setRestored(row.number);
      setError(null);
      // Экран не закрывается: подтверждение обязано остаться visible,
      // а уйти в редактор можно кнопкой сверху. Редактор при этом
      // перечитает проект заново — экран смонтируется с нуля.
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось восстановить версию.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="data vers">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Версии проекта</h1>
      </header>

      {error ? (
        <p className="data__error" role="alert">
          {error}
        </p>
      ) : null}
      {restored !== null ? (
        <p className="vers__ok" role="status">
          Проект возвращён к версии {restored}. Состояние, которое было на экране, сохранено
          как следующая версия — отменить восстановление можно из этого же списка.
        </p>
      ) : null}

      <section className="data__panel vers__mark">
        <h2 className="data__panel-title">Отметить состояние</h2>
        <p className="props__note">
          Снимок сохранит дерево целиком. Полезно перед крупной правкой: вернуться можно
          в любой момент, а история при этом не переписывается.
        </p>
        <div className="vers__mark-row">
          <input
            className="prop__input"
            value={label}
            maxLength={200}
            placeholder="Например: перед редизайном"
            onChange={(e) => setLabel(e.target.value)}
            aria-label="Подпись версии"
          />
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void mark()}
            disabled={busy}
          >
            Сохранить отметку
          </button>
        </div>
      </section>

      {rows === null ? (
        <p className="data__hint">Загружаем версии…</p>
      ) : rows.length === 0 ? (
        <section className="data__empty">
          <h2>Версий пока нет</h2>
          <p>
            Версия появляется при каждом сохранении изменений и вручную — по кнопке выше.
            Последние 50 версий хранятся, более старые удаляются.
          </p>
        </section>
      ) : (
        <section className="vers__list">
          <p className="data__hint">
            Текущая версия: {current}. Хранятся последние 50 снимков.
          </p>
          <ul>
            {rows.map((row) => (
              <li key={row.number} className="vers__row">
                <div className="vers__row-main">
                  <b>Версия {row.number}</b>
                  {row.label ? <span className="vers__row-label">{row.label}</span> : null}
                  <span className="vers__row-meta">
                    {when(row.createdAt)} · {row.author ?? 'система'} · блоков: {row.blocks}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => void restore(row)}
                  disabled={busy}
                  title="Вернуть проект к этому состоянию"
                >
                  Восстановить
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}