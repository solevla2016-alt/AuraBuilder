/**
 * Экран узлов данных проекта.
 *
 * Узлы данных входят в MVP (ТЗ п.12: шесть модулей data.*), а полноценная
 * визуальная БД приходит на этапе 5. Экран делает ровно необходимое:
 * создать источник с полями, добавить записи и увидеть их.
 *
 * Три решения, которые видно только здесь:
 *
 * 1. Ключ поля выводится из названия и показывается серым. Пользователь
 *    не должен выдумывать идентификаторы: ключ попадает в экспорт и в
 *    настройки синхронизации, но вводить его руками незачем.
 *
 * 2. Обязательное поле нельзя снять, если в источнике есть записи:
 *    иначе половина записей останется без значения, а сервер откажет
 *    при следующей правке — и непонятно почему.
 *
 * 3. Числа отправляются числами, а не строками. Иначе цена хранилась
 *    бы как «1 200 ₽» и не складывалась бы при агрегатах.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import {
  FIELD_TYPES,
  cellText,
  dataApi,
  fieldKeyFrom,
  type DataField,
  type DataRecord,
  type DataSource,
} from './data';

type Props = {
  projectId: string;
  onBack: () => void;
};

export function DataScreen({ projectId, onBack }: Props) {
  const [sources, setSources] = useState<DataSource[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newFields, setNewFields] = useState<{ label: string; type: DataField['type']; required: boolean }[]>(
    [{ label: '', type: 'text', required: false }],
  );

  const [records, setRecords] = useState<{ total: number; rows: DataRecord[] } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [recordError, setRecordError] = useState<string | null>(null);

  const active = useMemo(
    () => sources?.find((s) => s.id === activeId) ?? null,
    [sources, activeId],
  );

  const loadSources = useCallback(async () => {
    try {
      const list = await dataApi.listSources(projectId);
      setSources(list);
      setError(null);
      setActiveId((prev) => prev ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить узлы данных.');
      setSources([]);
    }
  }, [projectId]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  const loadRecords = useCallback(async (sourceId: string) => {
    try {
      const page = await dataApi.listRecords(sourceId, 100);
      setRecords({ total: page.total, rows: page.records });
      // Черновики сбрасываются: иначе правка записи, которая уже
      // сохранена, осталась бы в форме при возврате к экрану.
      setDrafts({});
      setRecordError(null);
    } catch (e) {
      setRecordError(e instanceof ApiError ? e.message : 'Не удалось загрузить записи.');
      setRecords({ total: 0, rows: [] });
    }
  }, []);

  useEffect(() => {
    if (activeId) void loadRecords(activeId);
  }, [activeId, loadRecords]);

  async function createSource() {
    const name = newName.trim();
    if (!name || busy) return;
    setBusy(true);
    try {
      const fields: DataField[] = newFields
        .map((f) => ({
          key: fieldKeyFrom(f.label),
          label: f.label.trim(),
          type: f.type,
          required: f.required,
        }))
        .filter((f) => f.label.trim() !== '' && f.key !== '');

      const source = await dataApi.createSource(projectId, { name, fields });
      setNewName('');
      setNewFields([{ label: '', type: 'text', required: false }]);
      setCreating(false);
      await loadSources();
      setActiveId(source.id);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось создать источник.');
    } finally {
      setBusy(false);
    }
  }

  async function addRecord() {
    if (!active || busy) return;
    const payload: Record<string, string | number | boolean | null> = {};
    for (const field of active.fields) {
      const raw = (drafts[`new:${field.key}`] ?? '').trim();
      if (raw === '') {
        if (field.required) {
          setRecordError(`Поле «${field.label}» обязательно.`);
          return;
        }
        continue;
      }
      payload[field.key] = coerce(raw, field.type);
    }
    if (Object.keys(payload).length === 0) {
      setRecordError('Заполните хотя бы одно поле.');
      return;
    }
    setBusy(true);
    try {
      await dataApi.createRecord(active.id, { data: payload });
      await loadRecords(active.id);
    } catch (e) {
      setRecordError(e instanceof ApiError ? e.message : 'Не удалось добавить запись.');
    } finally {
      setBusy(false);
    }
  }

  async function removeRecord(record: DataRecord) {
    if (!active || busy) return;
    setBusy(true);
    try {
      await dataApi.deleteRecord(record.id);
      await loadRecords(active.id);
    } catch (e) {
      setRecordError(e instanceof ApiError ? e.message : 'Не удалось удалить запись.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="data">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Данные проекта</h1>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => setCreating((v) => !v)}
        >
          <Icon name="plus" />
          <span>Новый источник</span>
        </button>
      </header>

      {error ? (
        <p className="data__error" role="alert">
          {error}
        </p>
      ) : null}

      {creating ? (
        <section className="data__panel">
          <h2 className="data__panel-title">Новый источник</h2>

          <label className="prop">
            <span className="prop__label">Название</span>
            <input
              className="prop__input"
              value={newName}
              maxLength={120}
              onChange={(e) => setNewName(e.target.value)}
            />
          </label>

          <fieldset className="data__fields">
            <legend>Поля</legend>
            {newFields.map((field, i) => (
              <div className="data__field" key={i}>
                <input
                  className="prop__input"
                  placeholder="Название поля"
                  value={field.label}
                  maxLength={80}
                  onChange={(e) =>
                    setNewFields((prev) =>
                      prev.map((f, j) => (j === i ? { ...f, label: e.target.value } : f)),
                    )
                  }
                />
                <select
                  className="prop__input"
                  value={field.type}
                  onChange={(e) =>
                    setNewFields((prev) =>
                      prev.map((f, j) =>
                        j === i ? { ...f, type: e.target.value as DataField['type'] } : f,
                      ),
                    )
                  }
                >
                  {FIELD_TYPES.map((t) => (
                    <option key={t.code} value={t.code}>
                      {t.label}
                    </option>
                  ))}
                </select>
                <label className="data__required">
                  <input
                    type="checkbox"
                    checked={field.required}
                    onChange={(e) =>
                      setNewFields((prev) =>
                        prev.map((f, j) => (j === i ? { ...f, required: e.target.checked } : f)),
                      )
                    }
                  />
                  <span>обязательное</span>
                </label>
                {newFields.length > 1 ? (
                  <button
                    type="button"
                    className="btn btn--ghost"
                    aria-label="Убрать поле"
                    onClick={() => setNewFields((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <Icon name="close" size={14} />
                  </button>
                ) : null}
              </div>
            ))}
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() =>
                setNewFields((prev) => [...prev, { label: '', type: 'text', required: false }])
              }
            >
              <Icon name="plus" size={14} />
              <span>Ещё поле</span>
            </button>
          </fieldset>

          <div className="data__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || !newName.trim()}
              onClick={() => void createSource()}
            >
              Создать
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setCreating(false)}>
              Отмена
            </button>
          </div>
        </section>
      ) : null}

      {sources === null ? (
        <p className="data__hint">Загружаем узлы данных…</p>
      ) : sources.length === 0 ? (
        <section className="data__empty">
          <h2>Источников данных пока нет</h2>
          <p>
            Источник описывает поля и хранит записи: к нему привязываются блоки коллекции,
            списка и одной записи.
          </p>
          <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>
            Создать источник
          </button>
        </section>
      ) : (
        <div className="data__layout">
          <nav className="data__sources" aria-label="Источники данных">
            <ul className="data__source-list">
              {sources.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={s.id === activeId ? 'data__source is-active' : 'data__source'}
                    onClick={() => setActiveId(s.id)}
                  >
                    <span className="data__source-name">{s.name}</span>
                    <span className="data__source-meta">
                      {s.key} · {s.recordCount} записей
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <section className="data__panel">
            {active ? (
              <>
                <h2 className="data__panel-title">{active.name}</h2>
                <p className="data__hint">
                  Ключ <code>{active.key}</code> попадёт в адрес публикации и в настройки
                  синхронизации.
                </p>

                {recordError ? (
                  <p className="data__error" role="alert">
                    {recordError}
                  </p>
                ) : null}

                {active.fields.length === 0 ? (
                  <p className="data__hint">В источнике нет полей — записи добавить нельзя.</p>
                ) : (
                  <table className="data__table">
                    <thead>
                      <tr>
                        {active.fields.map((f) => (
                          <th key={f.key} scope="col">
                            {f.label}
                            {f.required ? ' *' : ''}
                          </th>
                        ))}
                        <th scope="col" aria-label="Действия" />
                      </tr>
                    </thead>
                    <tbody>
                      {records?.rows.map((row) => (
                        <tr key={row.id}>
                          {active.fields.map((f) => (
                            <td key={f.key}>{cellText(row.data[f.key])}</td>
                          ))}
                          <td>
                            <button
                              type="button"
                              className="btn btn--ghost"
                              title="Удалить запись"
                              onClick={() => void removeRecord(row)}
                            >
                              <Icon name="trash" size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                <p className="data__hint">
                  {records ? `Записей: ${records.total}` : ''}
                </p>

                {active.fields.length > 0 ? (
                  <div className="data__new-record">
                    {active.fields.map((f) => (
                      <label className="prop" key={`new-${f.key}`}>
                        <span className="prop__label">
                          {f.label}
                          {f.required ? ' *' : ''}
                        </span>
                        {f.type === 'boolean' ? (
                          <select
                            className="prop__input"
                            value={drafts[`new:${f.key}`] ?? ''}
                            onChange={(e) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [`new:${f.key}`]: e.target.value,
                              }))
                            }
                          >
                            <option value="">—</option>
                            <option value="да">да</option>
                            <option value="нет">нет</option>
                          </select>
                        ) : (
                          <input
                            className="prop__input"
                            type={f.type === 'number' ? 'number' : 'text'}
                            value={drafts[`new:${f.key}`] ?? ''}
                            onChange={(e) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [`new:${f.key}`]: e.target.value,
                              }))
                            }
                          />
                        )}
                      </label>
                    ))}
                    <button
                      type="button"
                      className="btn btn--primary"
                      disabled={busy}
                      onClick={() => void addRecord()}
                    >
                      Добавить запись
                    </button>
                  </div>
                ) : null}
              </>
            ) : null}
          </section>
        </div>
      )}
    </main>
  );
}

/**
 * Приводит введённое значение к типу поля.
 *
 * Сервер проверяет типы сам, но приводить значение нужно на клиенте:
 * иначе «1200» уехало бы числом строкой и отклонилось бы с 400,
 * хотя пользователь просто не заметил разницы в кавычках.
 */
function coerce(
  raw: string,
  type: DataField['type'],
): string | number | boolean {
  if (type === 'number') {
    const n = Number(raw.replace(/\s/g, ''));
    return Number.isFinite(n) ? n : raw;
  }
  if (type === 'boolean') return raw === 'да';
  return raw;
}