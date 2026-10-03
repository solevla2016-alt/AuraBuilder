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
import type { Block } from './project';
import { kindOf } from './moduleRegistry';

export interface BlockPatch {
  label?: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  align?: Align;
  content?: string;
}

export type Align = 'left' | 'center' | 'right';

export interface PropertiesPanelProps {
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

export function PropertiesPanel({
  block,
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

        <label className="prop">
          <span className="prop__label">Название</span>
          <input
            type="text"
            className="prop__input"
            value={block.label}
            maxLength={200}
            onChange={(e) => onPatch({ label: e.target.value })}
          />
        </label>
      </section>

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