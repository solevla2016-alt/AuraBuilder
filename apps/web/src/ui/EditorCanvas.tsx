/**
 * Editor Canvas — вариант V1 «Floating Palette».
 *
 * Выбран в docs/UI-DECISIONS.md, раздел 3.1. Плавающая панель оставляет
 * максимум площади под холст: в конструкторе пользователь смотрит на
 * страницу, а не на интерфейс. Панель сворачивается в одну иконку.
 *
 * Особенности реализации:
 *  - холст рисуется на Konva, а не div: нужны координаты узлов,
 *    трансформации и будущий z-порядок блоков;
 *  - палитра позиционируется через CSS-переменные слоёв, а не z-index
 *    вразброс (в шаблонах он достигал 16);
 *  - инструменты — настоящие radio-элементы в role=radiogroup,
 *    а не div с обработчиками: работает клавиатура.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Layer, Rect, Stage, Text, Transformer } from 'react-konva';
import type Konva from 'konva';
import { Icon, type IconName } from './icons';
import './editor.css';

/* ------------------------------------------------------------------ */
/*  Инструменты                                                        */
/* ------------------------------------------------------------------ */

interface Tool {
  id: string;
  icon: IconName;
  label: string;
  hint: string;
}

const TOOLS: Tool[] = [
  { id: 'select', icon: 'cursor', label: 'Выбор', hint: 'Выделение элементов (V)' },
  { id: 'hand', icon: 'hand', label: 'Перемещение', hint: 'Двигать холст (H)' },
  { id: 'layers', icon: 'layers', label: 'Слои', hint: 'Дерево страницы (L)' },
  { id: 'modules', icon: 'box', label: 'Модули', hint: 'Библиотека модулей (M)' },
  { id: 'text', icon: 'type', label: 'Текст', hint: 'Текстовый блок (T)' },
  { id: 'image', icon: 'image', label: 'Медиа', hint: 'Изображение и видео (I)' },
  { id: 'data', icon: 'data', label: 'Данные', hint: 'Привязка к данным (D)' },
  { id: 'flow', icon: 'flow', label: 'Логика', hint: 'Граф правил (F)' },
];

/* ------------------------------------------------------------------ */
/*  Демо-сцена: временная сцена, пока нет загрузки проекта             */
/* ------------------------------------------------------------------ */

interface Block {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  kind: 'section' | 'text' | 'media';
  label: string;
}

/**
 * Данные-заглушка. На этапе 1 заменяется содержимым проекта из Control Plane;
 * формат повторит модель дерева из docs/MODULE-CATALOG.md.
 */
const DEMO_BLOCKS: Block[] = [
  { id: 'b1', x: 40, y: 40, width: 640, height: 200, kind: 'section', label: 'Первый экран' },
  { id: 'b2', x: 40, y: 264, width: 640, height: 64, kind: 'text', label: 'Заголовок' },
  { id: 'b3', x: 40, y: 352, width: 300, height: 180, kind: 'media', label: 'Изображение' },
  { id: 'b4', x: 364, y: 352, width: 316, height: 180, kind: 'text', label: 'Описание' },
];

/* ------------------------------------------------------------------ */
/*  Компонент                                                          */
/* ------------------------------------------------------------------ */

const PAGE_WIDTH = 720;

export function EditorCanvas() {
  const [tool, setTool] = useState('select');
  const [selectedId, setSelectedId] = useState<string | null>('b1');
  const [collapsed, setCollapsed] = useState(false);
  const stageRef = useRef<Konva.Stage>(null);
  const trRef = useRef<Konva.Transformer>(null);

  const selected = DEMO_BLOCKS.find((b) => b.id === selectedId) ?? null;

  // Трансформер подстраивается под выделенный узел. Без этого он
  // остаётся с прошлым размером после смены выделения.
  useEffect(() => {
    const tr = trRef.current;
    const stage = stageRef.current;
    if (!tr || !stage) return;
    if (selectedId) {
      const node = stage.findOne(`#${selectedId}`);
      tr.nodes(node ? [node] : []);
    } else {
      tr.nodes([]);
    }
    tr.getLayer()?.batchDraw();
  }, [selectedId]);

  const handleSelect = useCallback((id: string) => {
    setSelectedId((prev) => (prev === id ? null : id));
  }, []);

  // Клик по пустому месту снимает выделение. Тип события общий для мыши
  // и касания: Konva не различает их в KonvaEventObject.
  const handleStageClick = useCallback((e: Konva.KonvaEventObject<Event>) => {
    if (e.target === e.target.getStage()) setSelectedId(null);
  }, []);

  const kindFill: Record<Block['kind'], string> = {
    section: 'var(--accentSurfaceSubtle)',
    text: 'var(--panel)',
    media: 'var(--panelSunken)',
  };

  return (
    <div className="editor">
      <header className="top-bar" role="banner">
        <div className="top-bar__group">
          <span className="top-bar__brand">AuraBuilder</span>
          <span className="top-bar__sep" aria-hidden="true" />
          <span className="top-bar__project">Интернет-магазин «Цветы»</span>
        </div>
        <div className="top-bar__group">
          <button type="button" className="btn btn--ghost" aria-label="Отменить">
            <Icon name="undo" />
          </button>
          <button type="button" className="btn btn--ghost" aria-label="Повторить">
            <Icon name="redo" />
          </button>
          <span className="top-bar__sep" aria-hidden="true" />
          <button type="button" className="btn btn--ghost">
            <Icon name="history" />
            История
          </button>
          <button type="button" className="btn btn--primary">
            <Icon name="rocket" />
            Опубликовать
          </button>
        </div>
      </header>

      <div className="editor__body">
        <main className="canvas" aria-label="Холст редактора">
          <Stage
            ref={stageRef}
            width={PAGE_WIDTH}
            height={900}
            onClick={handleStageClick}
            onTap={handleStageClick}
          >
            <Layer>
              {/* Фон страницы пользователя — нейтральный, чтобы не тинтить дизайн */}
              <Rect
                x={0}
                y={0}
                width={PAGE_WIDTH}
                height={900}
                fill="var(--canvas)"
                cornerRadius={4}
                shadowColor="rgba(15,16,18,0.12)"
                shadowBlur={24}
                shadowOpacity={0.5}
                shadowOffsetY={4}
              />

              {DEMO_BLOCKS.map((b) => (
                <Rect
                  key={b.id}
                  id={b.id}
                  x={b.x}
                  y={b.y}
                  width={b.width}
                  height={b.height}
                  fill={kindFill[b.kind]}
                  stroke={selectedId === b.id ? 'var(--selectionBorder)' : 'var(--border)'}
                  strokeWidth={selectedId === b.id ? 2 : 1}
                  cornerRadius={8}
                  draggable={tool === 'select'}
                  onClick={() => handleSelect(b.id)}
                  onTap={() => handleSelect(b.id)}
                  onDragEnd={(e) => {
                    // Сохраняем позицию: без этого блок возвращается
                    // при первой перерисовке сцены.
                    b.x = e.target.x();
                    b.y = e.target.y();
                  }}
                />
              ))}

              {DEMO_BLOCKS.map((b) => (
                <Text
                  key={`${b.id}-label`}
                  x={b.x + 14}
                  y={b.y + 14}
                  text={b.label}
                  fontSize={13}
                  fontFamily="Inter, sans-serif"
                  fill="var(--textSecondary)"
                  listening={false}
                />
              ))}

              <Transformer
                ref={trRef}
                rotateEnabled={false}
                borderStroke="var(--selectionBorder)"
                anchorFill="var(--accentSurface)"
                anchorStroke="var(--selectionBorder)"
                anchorSize={10}
                anchorCornerRadius={2}
                padding={2}
                enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']}
                boundBoxFunc={(oldBox, newBox) =>
                  newBox.width < 40 || newBox.height < 24 ? oldBox : newBox
                }
              />
            </Layer>
          </Stage>
        </main>

        {/* Плавающая палитра — V1. Слой --layer-floating-palette. */}
        <div
          className={`palette ${collapsed ? 'palette--collapsed' : ''}`}
          style={{ zIndex: 'var(--layer-floating-palette)' }}
        >
          <button
            type="button"
            className="palette__toggle"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-controls="palette-tools"
            title={collapsed ? 'Развернуть инструменты' : 'Свернуть инструменты'}
          >
            <Icon name={collapsed ? 'chevronRight' : 'chevronDown'} />
            <span className="visually-hidden">
              {collapsed ? 'Развернуть инструменты' : 'Свернуть инструменты'}
            </span>
          </button>

          <div className="palette__body" id="palette-tools" hidden={collapsed}>
            <div className="palette__tools" role="radiogroup" aria-label="Инструменты">
              {TOOLS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="radio"
                  aria-checked={tool === t.id}
                  className={`palette__tool ${tool === t.id ? 'is-active' : ''}`}
                  onClick={() => setTool(t.id)}
                  title={`${t.label} — ${t.hint}`}
                >
                  <Icon name={t.icon} />
                  <span className="visually-hidden">{t.label}</span>
                </button>
              ))}
            </div>

            <div className="palette__meta">
              <span className="palette__hint">
                {TOOLS.find((t) => t.id === tool)?.hint}
              </span>
              {selected ? (
                <span className="palette__selection">
                  Выбрано: {selected.label}
                </span>
              ) : (
                <span className="palette__selection palette__selection--none">
                  Ничего не выбрано
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
