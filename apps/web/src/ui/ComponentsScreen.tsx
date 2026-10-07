/**
 * Экран библиотеки компонентов (ТЗ п.3.1).
 *
 * «Изюминка №1» по ТЗ: изменение стиля здесь обновляет компоненты на
 * всех страницах. Экран и есть тот один раз, когда стиль меняют.
 *
 * Что важно в интерфейсе:
 *
 * 1. Слева — список видов компонентов, справа — настройки выбранного.
 *    Видов три (секция, текст, медиа): столько же, сколько ролей у
 *    блока в макете. Пока видов мало, список держит экран понятным, а
 *    при добавлении четвёртого места в вёрстке не понадобится.
 *
 * 2. Образец компонента рисуется теми же значениями, что и холст:
 *    цвета берутся из палитры через CSS-переменные. Образец, собранный
 *    отдельно, рано или поздно разошёлся бы с макетом, и пользователь
 *    перестал бы ему верить.
 *
 * 3. Контраст проверяет сервер, а экран подсказывает заранее: список
 *    подходящих сочетаний уже отфильтрован. Отказ сервера при этом
 *    остаётся возможным — палитра пополняется, и проверка обязана быть
 *    на его стороне.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import {
  COLOR_LABELS,
  COLOR_TOKENS,
  COMPONENT_LABELS,
  MIN_CONTRAST,
  TEXT_TOKENS,
  colorValue,
  componentsApi,
  worstPairContrast,
  type ComponentKind,
  type ComponentStyle,
  type ComponentTokens,
} from './components';

type Props = {
  projectId: string;
  onBack: () => void;
};

type Draft = ComponentTokens & { background: string; text: string };

const NUMBERS: { key: 'radius' | 'padding' | 'weight' | 'border'; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: 'radius', label: 'Скругление', min: 0, max: 32, step: 1, hint: 'пикселей' },
  { key: 'padding', label: 'Внутренние поля', min: 0, max: 96, step: 2, hint: 'пикселей' },
  { key: 'weight', label: 'Насыщенность', min: 400, max: 800, step: 50, hint: '400–800' },
  { key: 'border', label: 'Рамка', min: 0, max: 4, step: 1, hint: 'пикселей' },
];

export function ComponentsScreen({ projectId, onBack }: Props) {
  const [styles, setStyles] = useState<Record<ComponentKind, ComponentStyle> | null>(null);
  const [activeKind, setActiveKind] = useState<ComponentKind>('section');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await componentsApi.list(projectId);
      setStyles({
        section: body.styles.find((s) => s.kind === 'section') as ComponentStyle,
        text: body.styles.find((s) => s.kind === 'text') as ComponentStyle,
        media: body.styles.find((s) => s.kind === 'media') as ComponentStyle,
      });
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить библиотеку.');
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const active = styles ? styles[activeKind] : null;

  // Черновик живёт, пока пользователь правит: перезаписывать его
  // каждым рендером означало бы терять несохранённые правки.
  useEffect(() => {
    setDraft(active ? { ...active.tokens } : null);
  }, [activeKind, active?.updatedAt]);

  // Контраст считается на лету: сервер всё равно проверит и откажет,
  // но пользователь должен увидеть причину до нажатия, а не после.
  const contrast = useMemo(() => {
    if (!draft) return null;
    return worstPairContrast(draft.background, draft.text);
  }, [draft]);

  const unreadable = contrast !== null && contrast < MIN_CONTRAST;

  const dirty = useMemo(() => {
    if (!draft || !active) return false;
    return (Object.keys(draft) as (keyof Draft)[]).some((k) => draft[k] !== active.tokens[k]);
  }, [draft, active]);

  async function save() {
    if (!draft || busy) return;
    setBusy(true);
    try {
      await componentsApi.save(projectId, activeKind, draft);
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить стиль.');
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (busy) return;
    setBusy(true);
    try {
      await componentsApi.reset(projectId, activeKind);
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сбросить стиль.');
    } finally {
      setBusy(false);
    }
  }

  const preview = useMemo(() => {
    if (!draft) return null;
    return {
      fill: colorValue(draft.background, '#FFFFFF'),
      text: colorValue(draft.text, '#1A1C1E'),
    };
  }, [draft]);

  return (
    <main className="data comps">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Библиотека компонентов</h1>
      </header>

      {error ? (
        <p className="data__error" role="alert">
          {error}
        </p>
      ) : null}

      {styles === null ? (
        <p className="data__hint">Загружаем библиотеку…</p>
      ) : (
        <div className="comps__layout">
          <nav className="comps__list" aria-label="Виды компонентов">
            {COMPONENT_LABELS.map((item) => {
              const style = styles[item.kind];
              return (
                <button
                  key={item.kind}
                  type="button"
                  className={`comps__item ${item.kind === activeKind ? 'is-active' : ''}`}
                  onClick={() => setActiveKind(item.kind)}
                >
                  <span
                    className="comps__swatch"
                    style={{ background: colorValue(style.tokens.background, '#FFF') }}
                  />
                  <span className="comps__item-name">{item.label}</span>
                  {style.isDefault ? (
                    <span className="comps__item-meta">по умолчанию</span>
                  ) : (
                    <span className="comps__item-meta">изменён</span>
                  )}
                </button>
              );
            })}
          </nav>

          <section className="data__panel">
            <h2 className="data__panel-title">
              {COMPONENT_LABELS.find((c) => c.kind === activeKind)?.label}
            </h2>
            <p className="props__note">
              {COMPONENT_LABELS.find((c) => c.kind === activeKind)?.hint}
            </p>

            <div className="comps__preview" aria-label="Образец компонента">
              {preview ? (
                <div
                  className="comps__sample"
                  style={{
                    background: preview.fill,
                    color: preview.text,
                    borderRadius: `${draft?.radius ?? 0}px`,
                    padding: `${draft?.padding ?? 0}px`,
                    borderWidth: `${draft?.border ?? 0}px`,
                    fontWeight: draft?.weight ?? 400,
                  }}
                >
                  <b>Заголовок компонента</b>
                  <span>Текст, который читается на этой подложке</span>
                </div>
              ) : (
                <p className="data__hint">Загружаем стиль…</p>
              )}
            </div>

            <div className="comps__fields">
              <label className="prop" htmlFor="comps-background">
                <span className="prop__label">Фон</span>
                <select
                  id="comps-background"
                  className="prop__input"
                  value={draft?.background ?? ''}
                  onChange={(e) => setDraft((d) => (d ? { ...d, background: e.target.value } : d))}
                >
                  {COLOR_TOKENS.map((token) => (
                    <option key={token} value={token}>
                      {COLOR_LABELS[token] ?? token}
                    </option>
                  ))}
                </select>
              </label>

              <label className="prop" htmlFor="comps-text">
                <span className="prop__label">Цвет текста</span>
                <select
                  id="comps-text"
                  className="prop__input"
                  value={draft?.text ?? ''}
                  onChange={(e) => setDraft((d) => (d ? { ...d, text: e.target.value } : d))}
                >
                  {TEXT_TOKENS.map((token) => (
                    <option key={token} value={token}>
                      {COLOR_LABELS[token] ?? token}
                    </option>
                  ))}
                </select>
                <span className="prop__hint">
                  Сервер не примет сочетание с контрастом ниже 4.5:1 ни в светлой,
                  ни в тёмной теме.
                </span>
              </label>

              {NUMBERS.map((field) => (
                <label className="prop" key={field.key} htmlFor={`comps-${field.key}`}>
                  <span className="prop__label">{field.label}</span>
                  <input
                    id={`comps-${field.key}`}
                    type="number"
                    className="prop__input"
                    min={field.min}
                    max={field.max}
                    step={field.step}
                    value={draft?.[field.key] ?? 0}
                    onChange={(e) => {
                      const next = Number(e.target.value);
                      // Пустое поле не должно превращаться в NaN: такое
                      // значение сервер отвергнет вместе со всем стилем.
                      if (Number.isFinite(next)) {
                        setDraft((d) => (d ? { ...d, [field.key]: next } : d));
                      }
                    }}
                  />
                  <span className="prop__hint">{field.hint}</span>
                </label>
              ))}
            </div>

            <div className="data__actions">
              {unreadable ? (
                <p className="props__note comps__warn" role="alert">
                  Контраст {contrast}:1 в худшей из тем — ниже порога {MIN_CONTRAST}:1.
                  Текст на этом фоне прочитать нельзя, сервер такой стиль не примет.
                </p>
              ) : null}

              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void save()}
                disabled={busy || !dirty || unreadable}
                title={unreadable ? 'Сначала выберите читаемый цвет текста' : undefined}
              >
                Сохранить стиль
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => void reset()}
                disabled={busy}
                title="Вернуть значения по умолчанию"
              >
                Сбросить
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}