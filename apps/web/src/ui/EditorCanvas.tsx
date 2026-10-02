/**
 * Editor Canvas — вариант V1 «Floating Palette».
 *
 * Выбран в docs/UI-DECISIONS.md, раздел 3.1. Плавающая панель оставляет
 * максимум площади под холст: в конструкторе пользователь смотрит на
 * страницу, а не на интерфейс. Панель сворачивается в одну иконку.
 *
 * Холст на Konva подгружается лениво (React.lazy): Konva — около 100 КБ
 * gzip, и в критическом пути первого экрана он съедал запас бюджета
 * LCP (ТЗ п.1.3). Панель и верхняя строка от Konva не зависят.
 *
 * Инструменты — настоящие role=radio, а не div с обработчиками:
 * работает клавиатура. z-index берётся из шкалы слоёв токенов.
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon, type IconName } from './icons';
import { api, ApiError } from './api';
import { defaultTree, type PageTree } from './project';
import './editor.css';

const Canvas = lazy(() => import('./Canvas'));

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
/*  Состояние сохранения                                               */
/* ------------------------------------------------------------------ */

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

const PROJECT_ID = '00000000-0000-4000-8000-000000000001';

/* ------------------------------------------------------------------ */
/*  Компонент                                                          */
/* ------------------------------------------------------------------ */

export function EditorCanvas() {
  const [tool, setTool] = useState('select');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [tree, setTree] = useState<PageTree>(() => defaultTree());
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const dirtyRef = useRef(false);

  const selected = useMemo(
    () => tree.blocks.find((b) => b.id === selectedId) ?? null,
    [tree.blocks, selectedId],
  );

  // Загрузка проекта при старте. При недоступном API остаётся дерево
  // по умолчанию и показывается причина: редактор должен открываться
  // и без бэкенда, иначе стенд 1С блокирует фронтенд-работу.
  useEffect(() => {
    let cancelled = false;
    api
      .getProject(PROJECT_ID)
      .then((p) => {
        if (cancelled) return;
        setTree(p.tree);
        dirtyRef.current = false;
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setSaveError(
          e instanceof ApiError
            ? `Control Plane недоступен (${e.status}). Работаем локально.`
            : 'Control Plane недоступен. Работаем локально.',
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleMove = useCallback((id: string, x: number, y: number) => {
    setTree((prev) => ({
      ...prev,
      blocks: prev.blocks.map((b) => (b.id === id ? { ...b, x, y } : b)),
    }));
    dirtyRef.current = true;
    setSaveState('idle');
  }, []);

  async function handleSave() {
    setSaveState('saving');
    setSaveError(null);
    try {
      const saved = await api.saveProject(
        PROJECT_ID,
        'Интернет-магазин «Цветы»',
        tree,
      );
      setTree(saved.tree);
      dirtyRef.current = false;
      setSaveState('saved');
    } catch (e) {
      setSaveError(
        e instanceof ApiError ? `Не сохранено: ${e.message}` : 'Не сохранено: сеть недоступна',
      );
      setSaveState('error');
    }
  }

  // Ctrl/Cmd+S — привычная комбинация для сохранения. Раньше в шаблонах
  // горячих клавиш не было вовсе.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        void handleSave();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const saveLabel =
    saveState === 'saving'
      ? 'Сохранение…'
      : saveState === 'saved'
        ? 'Сохранено'
        : dirtyRef.current
          ? 'Есть изменения'
          : 'Сохранить';

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
          <button
            type="button"
            className={`btn btn--ghost btn--save is-${saveState}`}
            onClick={() => void handleSave()}
            disabled={saveState === 'saving'}
          >
            <Icon name="check" />
            {saveLabel}
          </button>
          <button type="button" className="btn btn--primary">
            <Icon name="rocket" />
            Опубликовать
          </button>
        </div>
      </header>

      {saveError ? (
        <p className="banner banner--warn" role="status">
          <Icon name="settings" size={16} />
          {saveError}
        </p>
      ) : null}

      <div className="editor__body">
        <main className="canvas" aria-label="Холст редактора" aria-busy={loading}>
          <Suspense fallback={<div className="canvas__loading" role="status">Загрузка холста…</div>}>
            <Canvas
              blocks={tree.blocks}
              selectedId={selectedId}
              tool={tool}
              onSelect={setSelectedId}
              onMove={handleMove}
            />
          </Suspense>
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
              <span className="palette__hint">{TOOLS.find((t) => t.id === tool)?.hint}</span>
              <span
                className={`palette__selection ${selected ? '' : 'palette__selection--none'}`}
              >
                {selected ? `Выбрано: ${selected.label}` : 'Ничего не выбрано'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
