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
 *
 * 4. Кроме токенов палитры можно задать свой #RRGGBB: фирменные цвета
 *    почти никогда не совпадают с палитрой продукта. Чтобы такой цвет не
 *    приводил к нечитаемому тексту, рядом есть «фирменный акцент» —
 *    одна кнопка ставит фон и подбирает контрастный текст автоматически.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import { api } from './api';
import type { ProjectBrand } from './project';
import {
  COLOR_LABELS,
  COLOR_TOKENS,
  COMPONENT_LABELS,
  MIN_CONTRAST,
  TEXT_TOKENS,
  colorValue,
  componentsApi,
  isHexColor,
  readableText,
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

/** Пустой брендбук: поля заполнены, но ничего не меняют. */
const EMPTY_BRAND: ProjectBrand = {
  accent: '',
  font: 'sans',
  signature: '',
  utmSource: '',
  utmMedium: '',
  utmCampaign: '',
};

const BRAND_FONTS: { id: ProjectBrand['font']; label: string }[] = [
  { id: 'sans', label: 'Inter / системный' },
  { id: 'system', label: 'Системный' },
  { id: 'serif', label: 'С засечками' },
  { id: 'mono', label: 'Моноширинный' },
];

/** Поля UTM: три метки, которые одинаковы для всех внешних ссылок. */
const UTM_FIELDS: {
  key: 'utmSource' | 'utmMedium' | 'utmCampaign';
  label: string;
  placeholder: string;
}[] = [
  { key: 'utmSource', label: 'Источник (utm_source)', placeholder: 'site' },
  { key: 'utmMedium', label: 'Канал (utm_medium)', placeholder: 'social' },
  { key: 'utmCampaign', label: 'Кампания (utm_campaign)', placeholder: 'autumn' },
];

/**
 * Перерисовка при смене темы.
 *
 * colorValue читает CSS-переменные в момент рендера, а data-theme
 * выставляется эффектом — то есть уже после него. Без счётчика образец
 * компонента и квадратики списка оставались бы в цветах прошлой темы до
 * следующего изменения черновика.
 */
function useThemeTick(): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setTick((n) => n + 1));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
    return () => observer.disconnect();
  }, []);
  return tick;
}


const NUMBERS: { key: 'radius' | 'padding' | 'weight' | 'border'; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: 'radius', label: 'Скругление', min: 0, max: 32, step: 1, hint: 'пикселей' },
  { key: 'padding', label: 'Внутренние поля', min: 0, max: 96, step: 2, hint: 'пикселей' },
  { key: 'weight', label: 'Насыщенность', min: 400, max: 800, step: 50, hint: '400–800' },
  { key: 'border', label: 'Рамка', min: 0, max: 4, step: 1, hint: 'пикселей' },
];

/** Готовые фирменные цвета: акцент выбирается в один клик, без подбора hex. */
const DEFAULT_ACCENT = '#4F46E5';

const BRAND_ACCENTS: { name: string; value: string }[] = [
  { name: 'Индиго', value: DEFAULT_ACCENT },
  { name: 'Синий', value: '#2563EB' },
  { name: 'Бирюзовый', value: '#0D9488' },
  { name: 'Зелёный', value: '#15803D' },
  { name: 'Оранжевый', value: '#EA580C' },
  { name: 'Розовый', value: '#DB2777' },
  { name: 'Графит', value: '#334155' },
];

type ColorFieldProps = {
  id: string;
  label: string;
  hint: string;
  /** Имя токена палитры или свой #RRGGBB. */
  value: string;
  tokens: readonly string[];
  onChange: (next: string) => void;
  /** Дополнительное действие строкой: например, подобрать контрастный текст. */
  action?: { label: string; title: string; onClick: () => void } | undefined;
};

/**
 * Поле «токен палитры или свой #RRGGBB».
 *
 * Текст в поле ввода хранится отдельно от черновика: валидным цвет
 * становится только на седьмом символе, и запись каждого нажатия в
 * черновик затирала бы недописанное значение. В черновик попадает лишь
 * законченный цвет, а недописанный откатывается при уходе из поля.
 */
function ColorField({ id, label, hint, value, tokens, onChange, action }: ColorFieldProps) {
  const custom = isHexColor(value);
  const [text, setText] = useState(custom ? value.toUpperCase() : '');

  useEffect(() => {
    setText(isHexColor(value) ? value.toUpperCase() : '');
  }, [value]);

  return (
    <div className="prop">
      <label className="prop__label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="prop__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {tokens.map((token) => (
          <option key={token} value={token}>
            {COLOR_LABELS[token] ?? token}
          </option>
        ))}
        {/* Свой цвет вне палитры: без отдельной строки select показал бы
            пустоту, и пользователь решил бы, что значение сбросилось. */}
        {custom ? <option value={value}>Свой цвет {value.toUpperCase()}</option> : null}
      </select>

      <div className="comps__color-row">
        <input
          type="color"
          className="comps__color"
          value={custom ? value : colorValue(value, '#FFFFFF')}
          aria-label={`${label}: палитра цветов`}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
        />
        <input
          type="text"
          className="prop__input comps__hex"
          value={text}
          placeholder="#RRGGBB"
          maxLength={7}
          spellCheck={false}
          aria-label={`${label}: свой цвет #RRGGBB`}
          onChange={(e) => {
            const next = e.target.value;
            setText(next);
            if (isHexColor(next.trim())) onChange(next.trim().toUpperCase());
          }}
          onBlur={() => {
            if (!isHexColor(text.trim())) setText(isHexColor(value) ? value.toUpperCase() : '');
          }}
        />
        {action ? (
          <button
            type="button"
            className="btn btn--ghost comps__auto"
            title={action.title}
            onClick={action.onClick}
          >
            {action.label}
          </button>
        ) : null}
      </div>
      <span className="prop__hint">{hint}</span>
    </div>
  );
}

export function ComponentsScreen({ projectId, onBack }: Props) {
  const [styles, setStyles] = useState<Record<ComponentKind, ComponentStyle> | null>(null);
  const [activeKind, setActiveKind] = useState<ComponentKind>('section');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [brand, setBrand] = useState<ProjectBrand | null>(null);
  const [brandBusy, setBrandBusy] = useState(false);
  const [brandNotice, setBrandNotice] = useState<string | null>(null);
  const themeTick = useThemeTick();

  // Фирменный акцент живёт отдельно от черновика: клик по образцу не
  // должен менять фон и текст до того, как пользователь нажмёт кнопку.
  const [accent, setAccent] = useState(DEFAULT_ACCENT);
  const [accentText, setAccentText] = useState(DEFAULT_ACCENT);

  function chooseAccent(next: string) {
    setAccent(next.toLowerCase());
    setAccentText(next.toUpperCase());
  }

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

  /**
   * Брендбук читается из проекта отдельным запросом: библиотека
   * компонентов отвечает за вид компонентов, а фирменный цвет, шрифт и
   * подпись — принадлежность проекта. Сервер всегда отдаёт полный
   * набор, поэтому пустой ответ заменяется значениями по умолчанию.
   */
  const loadBrand = useCallback(async () => {
    try {
      const project = await api.getProject(projectId);
      setBrand(project.brand ?? EMPTY_BRAND);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить брендбук.');
    }
  }, [projectId]);

  useEffect(() => {
    void loadBrand();
  }, [loadBrand]);

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

  /** Точечная правка брендбука: остальные поля не трогаются. */
  function updateBrand(patch: Partial<ProjectBrand>) {
    setBrand((current) => (current ? { ...current, ...patch } : current));
    setBrandNotice(null);
  }

  async function saveBrand() {
    if (!brand || brandBusy) return;
    setBrandBusy(true);
    try {
      const saved = await api.saveBrand(projectId, brand);
      setBrand(saved.brand ?? brand);
      setBrandNotice('Брендбук сохранён');
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить брендбук.');
    } finally {
      setBrandBusy(false);
    }
  }

  /**
   * Фирменный акцент одной кнопкой: фон — выбранный цвет, текст —
   * автоматически самый контрастный. Сохраняем сразу: акцент — это
   * решение «так и должно быть на сайте», а не черновик для сравнения.
   * Прочие правки черновика сохраняются вместе с ним, как и при обычном
   * нажатии «Сохранить стиль».
   */
  async function applyAccent() {
    if (!draft || busy || !isHexColor(accent)) return;
    const next: Draft = {
      ...draft,
      background: accent.toUpperCase(),
      text: readableText(accent),
    };
    setDraft(next);
    setBusy(true);
    try {
      await componentsApi.save(projectId, activeKind, next);
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось применить акцент.');
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
    // themeTick в зависимостях: значения токенов перечитываются после
    // смены темы, хотя сам черновик не изменился.
  }, [draft, themeTick]);

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

      {brand ? (
        <section className="data__panel brand" aria-label="Брендбук проекта">
          <h2 className="data__panel-title">Брендбук проекта</h2>
          <p className="props__note">
            Действует на всех страницах: цвет кнопок и ссылок, шрифт и подпись
            внизу. Пустой акцент оставляет цвет палитры.
          </p>

          <div className="brand__grid">
            <div className="prop">
              <span className="prop__label">Фирменный цвет</span>
              <div className="comps__color-row">
                <input
                  type="color"
                  className="comps__color"
                  aria-label="Фирменный цвет брендбука"
                  value={isHexColor(brand.accent) ? brand.accent : '#D9A441'}
                  onChange={(e) => updateBrand({ accent: e.target.value.toUpperCase() })}
                />
                <input
                  type="text"
                  className="prop__input comps__hex"
                  value={brand.accent}
                  placeholder="#RRGGBB"
                  maxLength={7}
                  spellCheck={false}
                  aria-label="Фирменный цвет: значение #RRGGBB"
                  onChange={(e) => updateBrand({ accent: e.target.value })}
                />
                <button
                  type="button"
                  className="btn btn--ghost btn--tiny"
                  onClick={() => updateBrand({ accent: '' })}
                  title="Вернуть цвет палитры"
                >
                  Сбросить
                </button>
              </div>
              <span className="prop__hint">
                Цвет кнопок и акцентных плашек. Пустое значение — цвет палитры.
              </span>
            </div>

            <label className="prop" htmlFor="brand-font">
              <span className="prop__label">Шрифт</span>
              <select
                id="brand-font"
                className="prop__input"
                value={brand.font}
                onChange={(e) =>
                  updateBrand({ font: e.target.value as ProjectBrand['font'] })
                }
              >
                {BRAND_FONTS.map((font) => (
                  <option key={font.id} value={font.id}>
                    {font.label}
                  </option>
                ))}
              </select>
              <span className="prop__hint">
                Только системные семейства: пакет должен открываться без интернета.
              </span>
            </label>

            <label className="prop brand__wide" htmlFor="brand-signature">
              <span className="prop__label">Подпись внизу страницы</span>
              <textarea
                id="brand-signature"
                className="props__textarea"
                rows={2}
                maxLength={300}
                value={brand.signature}
                placeholder="ООО «Ромашка», ИНН 7700000000"
                onChange={(e) => updateBrand({ signature: e.target.value })}
              />
              <span className="prop__hint">
                До 300 символов. Пустое поле не выводит подпись.
              </span>
            </label>

            {UTM_FIELDS.map((field) => (
              <label className="prop" key={field.key} htmlFor={`brand-${field.key}`}>
                <span className="prop__label">{field.label}</span>
                <input
                  id={`brand-${field.key}`}
                  type="text"
                  className="prop__input"
                  value={brand[field.key]}
                  placeholder={field.placeholder}
                  maxLength={80}
                  spellCheck={false}
                  onChange={(e) =>
                    updateBrand({
                      [field.key]: e.target.value,
                    } as Partial<ProjectBrand>)
                  }
                />
              </label>
            ))}
          </div>

          <p className="props__note">
            UTM-метки ставятся только на внешние абсолютные ссылки. Свой домен
            и ссылки с уже готовыми метками не трогаются.
          </p>

          <div className="data__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={brandBusy}
              onClick={() => void saveBrand()}
            >
              Сохранить брендбук
            </button>
            {brandNotice ? (
              <span className="prop__hint" role="status">
                {brandNotice}
              </span>
            ) : null}
          </div>
        </section>
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
              {draft ? (
                <>
                  <ColorField
                    id="comps-background"
                    label="Фон"
                    hint="Токен палитры подстраивается под тему сайта, свой цвет одинаков в обеих."
                    value={draft.background}
                    tokens={COLOR_TOKENS}
                    onChange={(next) =>
                      setDraft((d) => (d ? { ...d, background: next } : d))
                    }
                  />

                  <ColorField
                    id="comps-text"
                    label="Цвет текста"
                    hint="Сервер не примет сочетание с контрастом ниже 4.5:1 ни в светлой, ни в тёмной теме."
                    value={draft.text}
                    tokens={TEXT_TOKENS}
                    onChange={(next) => setDraft((d) => (d ? { ...d, text: next } : d))}
                    action={
                      isHexColor(draft.background)
                        ? {
                            label: 'Подобрать',
                            title: 'Подставить самый контрастный текст к выбранному фону',
                            onClick: () =>
                              setDraft((d) =>
                                d ? { ...d, text: readableText(d.background) } : d,
                              ),
                          }
                        : undefined
                    }
                  />
                </>
              ) : null}

              <div className="comps__accent">
                <div className="comps__accent-head">
                  <span className="prop__label">Фирменный акцент</span>
                  <span className="comps__accent-value">{accent.toUpperCase()}</span>
                </div>

                <div className="comps__swatches" role="group" aria-label="Готовые фирменные цвета">
                  {BRAND_ACCENTS.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className={`comps__swatch-btn ${
                        accent.toLowerCase() === item.value.toLowerCase() ? 'is-active' : ''
                      }`}
                      style={{ background: item.value }}
                      title={item.name}
                      aria-label={item.name}
                      aria-pressed={accent.toLowerCase() === item.value.toLowerCase()}
                      onClick={() => chooseAccent(item.value)}
                    />
                  ))}
                </div>

                <div className="comps__color-row">
                  <input
                    type="color"
                    className="comps__color"
                    value={accent}
                    aria-label="Фирменный цвет: палитра цветов"
                    onChange={(e) => chooseAccent(e.target.value)}
                  />
                  <input
                    type="text"
                    className="prop__input comps__hex"
                    value={accentText}
                    placeholder="#RRGGBB"
                    maxLength={7}
                    spellCheck={false}
                    aria-label="Фирменный цвет: значение #RRGGBB"
                    onChange={(e) => {
                      const next = e.target.value;
                      setAccentText(next);
                      if (isHexColor(next.trim())) setAccent(next.trim().toLowerCase());
                    }}
                    onBlur={() => {
                      if (!isHexColor(accentText.trim())) setAccentText(accent.toUpperCase());
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn--primary comps__auto"
                    disabled={busy || !draft}
                    onClick={() => void applyAccent()}
                  >
                    Применить акцент
                  </button>
                </div>

                <span className="prop__hint">
                  Фон станет выбранным цветом, текст — самым контрастным из белого и
                  почти чёрного. Сохраняется сразу, одной кнопкой.
                </span>
              </div>

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