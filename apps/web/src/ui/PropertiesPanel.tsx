/**
 * Контекстная панель свойств блока.
 *
 * ТЗ п.5.4: у элемента открывается контекстная панель с настройками.
 * UX-правило «3 клика»: выделить блок и поменять свойство — два
 * действия, третье — сохранить.
 *
 * Набор полей зависит от вида блока, а не от модуля: 65 модулей с
 * уникальными схемами появились бы на этапе 3, а редактор должен
 * работать уже сейчас. Общие поля (размеры, отступы, выравнивание)
 * есть у всех блоков; для текстовых добавляется содержимое.
 *
 * Панель не пишет напрямую в дерево: изменения собираются в патч и
 * отдаются наверх одним действием, чтобы каждое нажатие было одной
 * записью в истории.
 */

import { useEffect, useState } from 'react';
import { Icon } from './icons';
import { dataApi, type DataSource } from './data';
import type { Block } from './project';
import { kindOf, schemaFor } from './moduleRegistry';
import type { PropDef } from './moduleRegistry';

export interface BlockPatch {
  label?: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  align?: Align;
  content?: string;
  /** Схема свойств модуля: приходит целиком, а не по полям. */
  props?: Record<string, string | number | boolean>;
}

export type Align = 'left' | 'center' | 'right';

export interface PropertiesPanelProps {
  /** Проект нужен для списка источников данных. */
  projectId?: string;
  block: Block | null;
  /** Содержимое блока: хранится рядом с блоком, в дереве пока нет. */
  content: string;
  onPatch: (patch: BlockPatch) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onCopyStyle: () => void;
  /** Есть ли блок, у которого можно взять настройки. */
  canPasteStyle: boolean;
  onPasteStyle: () => void;
}

const ALIGNS: { id: Align; icon: 'alignLeft' | 'alignCenter' | 'alignRight'; label: string }[] = [
  { id: 'left', icon: 'alignLeft', label: 'По левому краю' },
  { id: 'center', icon: 'alignCenter', label: 'По центру' },
  { id: 'right', icon: 'alignRight', label: 'По правому краю' },
];

/** Шаг изменения координат при вводе с клавиатуры, пиксели. */
const STEP = 4;

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <label className="prop">
      <span className="prop__label">{label}</span>
      <input
        type="number"
        className="prop__input"
        value={Math.round(value)}
        min={min}
        max={max}
        step={STEP}
        onChange={(e) => {
          const next = Number(e.target.value);
          // Пустое поле и мусор в поле не должны превращаться в NaN:
          // такое значение сервер потом отвергнет вместе со всем деревом.
          if (Number.isFinite(next)) onChange(next);
        }}
      />
    </label>
  );
}

function SchemaField({
  prop,
  value,
  onChange,
}: {
  prop: PropDef;
  value: string | number | boolean | undefined;
  onChange: (v: string | number | boolean) => void;
}) {
  const id = `prop-${prop.name}`;

  if (prop.type === 'boolean') {
    return (
      <label className="prop prop--row" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="prop__label">{prop.name}</span>
      </label>
    );
  }

  if (prop.type === 'select') {
    const options = prop.limits.options ?? [];
    return (
      <label className="prop" htmlFor={id}>
        <span className="prop__label">{prop.name}</span>
        <select
          id={id}
          className="prop__input"
          value={String(value ?? prop.default ?? options[0] ?? '')}
          onChange={(e) => onChange(e.target.value)}
        >
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (prop.type === 'textarea') {
    return (
      <label className="prop" htmlFor={id}>
        <span className="prop__label">{prop.name}</span>
        <textarea
          id={id}
          className="props__textarea"
          rows={2}
          maxLength={5000}
          value={String(value ?? prop.default ?? '')}
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => onChange(e.target.value)}
        />
      </label>
    );
  }

  return (
    <label className="prop" htmlFor={id}>
      <span className="prop__label">{prop.name}</span>
      <input
        id={id}
        className="prop__input"
        type={prop.type === 'number' ? 'number' : 'text'}
        min={prop.limits.min}
        max={prop.limits.max}
        step={prop.limits.step}
        maxLength={prop.type === 'number' ? undefined : 200}
        value={String(value ?? prop.default ?? '')}
        onChange={(e) => {
          // Пустое поле не должно превращаться в NaN: такое значение
          // сервер отвергнет вместе со всем деревом.
          if (prop.type === 'number') {
            const n = Number(e.target.value);
            if (Number.isFinite(n)) onChange(n);
            return;
          }
          onChange(e.target.value);
        }}
      />
    </label>
  );
}

/**
 * Источники данных проекта для поля source.
 *
 * Список грузится один раз на проект. Когда источников нет или сервер
 * недоступен, поле остаётся с единственным вариантом «не выбран»:
 * молча подставлять первый источник значило бы привязать блок к
 * чужим данным без спроса.
 */
function useSources(projectId: string | undefined): DataSource[] {
  const [sources, setSources] = useState<DataSource[]>([]);
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void dataApi
      .listSources(projectId)
      .then((list) => {
        if (!cancelled) setSources(list);
      })
      .catch(() => {
        // Недоступный список не должен ломать панель: остальные
        // свойства модуля продолжают работать.
        if (!cancelled) setSources([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);
  return sources;
}

function SourcePicker({
  value,
  sources,
  onChange,
}: {
  value: string;
  sources: DataSource[];
  onChange: (v: string) => void;
}) {
  const selected = sources.find((s) => s.id === value);
  return (
    <label className="prop" htmlFor="prop-source">
      <span className="prop__label">Источник данных</span>
      <select
        id="prop-source"
        className="prop__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">— не выбран —</option>
        {sources.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} ({s.recordCount})
          </option>
        ))}
      </select>
      {selected ? (
        <span className="prop__hint">
          {selected.recordCount} записей, полей: {selected.fields.length}
        </span>
      ) : null}
    </label>
  );
}

export function PropertiesPanel({
  block,
  projectId,
  content,
  onPatch,
  onDuplicate,
  onDelete,
  onCopyStyle,
  canPasteStyle,
  onPasteStyle,
}: PropertiesPanelProps) {
  const [draftContent, setDraftContent] = useState(content);

  // Черновик содержимого живёт, пока пользователь печатает: обновлять
  // дерево на каждую букву значило бы засорять историю.
  useEffect(() => {
    setDraftContent(content);
  }, [content, block?.id]);

  if (!block) {
    return (
      <div className="props props--empty" role="status">
        <p>Выберите блок, чтобы открыть его настройки</p>
      </div>
    );
  }

  // Вид блока выводится из модуля: section — секция, text и media —
  // плоские блоки. Хранить его в данных блока нельзя, он разошёлся бы
  // с реестром модулей.
  const isText = kindOf(block.module) === 'text';

  const sources = useSources(projectId);

  // Схема свойств приходит из реестра: панель не знает модулей.
  // Пока схема описана для трёх модулей MVP, у остальных её нет и
  // показывается общий набор полей.
  const schema = schemaFor(block.module);

  return (
    <div className="props">
      <header className="props__head">
        <div className="props__title">
          <b>{block.label || 'Блок'}</b>
          <code>{block.module}</code>
        </div>
      </header>

      <section className="props__group">
        <h3>Содержимое</h3>
        {isText ? (
          <textarea
            className="props__textarea"
            value={draftContent}
            rows={3}
            placeholder="Текст блока"
            onChange={(e) => setDraftContent(e.target.value)}
            onBlur={() => {
              if (draftContent !== content) onPatch({ content: draftContent });
            }}
          />
        ) : (
          <p className="props__note">
            Этот модуль наполняется данными на этапе 3. Сейчас доступны
            размеры и положение.
          </p>
        )}

        <label className="prop" htmlFor="block-label">
          <span className="prop__label">Название</span>
          <input
            id="block-label"
            type="text"
            className="prop__input"
            value={block.label}
            maxLength={200}
            onChange={(e) => onPatch({ label: e.target.value })}
          />
        </label>
      </section>

      {schema ? (
        <section className="props__group">
          <h3>Свойства модуля</h3>
          {schema.props.map((prop) =>
            prop.name === 'source' ? (
              <SourcePicker
                key={prop.name}
                value={
                  typeof block.props?.[prop.name] === 'string'
                    ? (block.props[prop.name] as string)
                    : ''
                }
                sources={sources}
                onChange={(v) => onPatch({ props: { ...(block.props ?? {}), source: v } })}
              />
            ) : (
              <SchemaField
                key={prop.name}
                prop={prop}
                value={block.props?.[prop.name]}
                onChange={(v) =>
                  onPatch({ props: { ...(block.props ?? {}), [prop.name]: v } })
                }
              />
            ),
          )}
        </section>
      ) : null}

      <section className="props__group">
        <h3>Положение и размер</h3>
        <div className="props__grid">
          <NumberField
            label="X"
            value={block.x}
            min={0}
            onChange={(x) => onPatch({ x })}
          />
          <NumberField
            label="Y"
            value={block.y}
            min={0}
            onChange={(y) => onPatch({ y })}
          />
          <NumberField
            label="Ширина"
            value={block.width}
            min={1}
            onChange={(width) => onPatch({ width })}
          />
          <NumberField
            label="Высота"
            value={block.height}
            min={1}
            onChange={(height) => onPatch({ height })}
          />
        </div>
      </section>

      <section className="props__group">
        <h3>Выравнивание</h3>
        <div className="props__aligns" role="radiogroup" aria-label="Выравнивание содержимого">
          {ALIGNS.map((a) => (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={(block.align ?? 'left') === a.id}
              className={`props__align ${(block.align ?? 'left') === a.id ? 'is-active' : ''}`}
              onClick={() => onPatch({ align: a.id })}
              title={a.label}
            >
              <Icon name={a.icon} size={18} />
              <span className="visually-hidden">{a.label}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="props__group props__actions">
        <button type="button" className="btn btn--ghost" onClick={onCopyStyle}>
          <Icon name="duplicate" size={16} />
          Копировать стиль
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onPasteStyle}
          disabled={!canPasteStyle}
          title={canPasteStyle ? 'Применить скопированный стиль' : 'Сначала скопируйте стиль блока'}
        >
          <Icon name="check" size={16} />
          Вставить стиль
        </button>
        <button type="button" className="btn btn--ghost" onClick={onDuplicate}>
          <Icon name="plus" size={16} />
          Дублировать
        </button>
        <button type="button" className="btn btn--ghost btn--danger" onClick={onDelete}>
          <Icon name="trash" size={16} />
          Удалить
        </button>
      </section>
    </div>
  );
}