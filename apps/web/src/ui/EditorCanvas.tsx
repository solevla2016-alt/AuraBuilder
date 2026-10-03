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
import { defaultTree, newBlockId, validateTree, type Block, type PageTree } from './project';
import { MODULE_CATEGORIES, MODULES, kindOf } from './moduleRegistry';
import type { ModuleDef } from './moduleRegistry';
import { ModulePalette } from './ModulePalette';
import { PropertiesPanel, type Align, type BlockPatch } from './PropertiesPanel';
import { useHistory } from './useHistory';
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

/**
 * Этап выпуска, для которого показываются модули.
 * На стенде это MVP — этап 3 из ТЗ п.12.
 */
const CURRENT_STAGE = 3;

/* ------------------------------------------------------------------ */
/*  Компонент                                                          */
/* ------------------------------------------------------------------ */

export function EditorCanvas() {
  const [tool, setTool] = useState('select');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const dirtyRef = useRef(false);

  // Дерево живёт в истории: каждое действие — одна запись, Ctrl+Z
  // откатывает действие целиком, а не доли пикселя.
  const history = useHistory<PageTree>(defaultTree());
  const tree = history.value;

  // Настройки скопированного блока для «кисточки». Хранятся отдельно от
  // дерева: это временное состояние интерфейса, а не содержимое страницы.
  const [copiedStyle, setCopiedStyle] = useState<{
    align: Align;
    width: number;
    height: number;
    content: string;
  } | null>(null);

  // Каталог модулей: сначала локальный реестр, чтобы палитра появилась
  // мгновенно, затем ответ Control Plane — он авторитетен.
  const [modules, setModules] = useState<ModuleDef[]>(() => MODULES);
  const [modulesLoading, setModulesLoading] = useState(false);
  const [category, setCategory] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setModulesLoading(true);
    api
      .getModules(CURRENT_STAGE)
      .then((c) => {
        if (!cancelled && c.modules.length > 0) setModules(c.modules);
      })
      .catch(() => {
        // Локальный реестр остаётся: палитра должна работать и без сети.
      })
      .finally(() => {
        if (!cancelled) setModulesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
        // reset, а не commit: то, что пришло с сервера, не должно
        // попадать в историю и отменяться по Ctrl+Z.
        history.reset(p.tree);
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
    // history.reset стабилен по useCallback, но включать весь объект
    // истории в зависимости означало бы перезапуск запроса при отмене.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const markDirty = useCallback(() => {
    dirtyRef.current = true;
    setSaveState('idle');
  }, []);

  const handleMove = useCallback(
    (id: string, x: number, y: number) => {
      // Один жест перетаскивания — одна запись в истории: onDragEnd
      // срабатывает по завершении, а не на каждом кадре.
      history.commit({
        ...tree,
        blocks: tree.blocks.map((b) => (b.id === id ? { ...b, x, y } : b)),
      });
      markDirty();
    },
    [history, tree, markDirty],
  );

  /** Применение патча к выбранному блоку. */
  const applyPatch = useCallback(
    (patch: BlockPatch) => {
      if (!selectedId) return;
      history.commit({
        ...tree,
        blocks: tree.blocks.map((b) => {
          if (b.id !== selectedId) return b;
          const next: Block = { ...b };
          if (patch.label !== undefined) next.label = patch.label;
          if (patch.align !== undefined) next.align = patch.align;
          if (patch.content !== undefined) next.content = patch.content;
          if (patch.width !== undefined) next.width = Math.max(1, patch.width);
          if (patch.height !== undefined) next.height = Math.max(1, patch.height);
          if (patch.x !== undefined) next.x = Math.max(0, patch.x);
          if (patch.y !== undefined) next.y = Math.max(0, patch.y);
          return next;
        }),
      });
      markDirty();
    },
    [history, tree, selectedId, markDirty],
  );

  const deleteSelected = useCallback(() => {
    if (!selectedId) return;
    history.commit({
      ...tree,
      blocks: tree.blocks.filter((b) => b.id !== selectedId),
    });
    setSelectedId(null);
    markDirty();
  }, [history, tree, selectedId, markDirty]);

  const duplicateSelected = useCallback(() => {
    if (!selected) return;
    // Дубликат ставится правее оригинала: так видно, что он новый,
    // и исходный блок не перекрывается.
    const copy: Block = {
      ...selected,
      id: newBlockId(),
      x: Math.min(selected.x + 24, Math.max(0, tree.width - selected.width)),
      y: selected.y + selected.height + 24,
    };
    history.commit({ ...tree, blocks: [...tree.blocks, copy] });
    setSelectedId(copy.id);
    markDirty();
  }, [history, tree, selected, markDirty]);

  const copyStyle = useCallback(() => {
    if (!selected) return;
    setCopiedStyle({
      align: selected.align ?? 'left',
      width: selected.width,
      height: selected.height,
      content: selected.content ?? '',
    });
  }, [selected]);

  const pasteStyle = useCallback(() => {
    if (!selected || !copiedStyle) return;
    history.commit({
      ...tree,
      blocks: tree.blocks.map((b) => {
        if (b.id !== selectedId) return b;
        // Содержимое переносится только в текстовый блок: иначе
        // текст из заголовка оказался бы внутри секции.
        const next: Block = {
          ...b,
          align: copiedStyle.align,
          width: copiedStyle.width,
          height: copiedStyle.height,
        };
        if (kindOf(b.module) === 'text') next.content = copiedStyle.content;
        return next;
      }),
    });
    markDirty();
  }, [history, tree, selected, selectedId, copiedStyle, markDirty]);

  /**
   * Вставка модуля. Новый блок ставится под последним на странице —
   * это соответствует «inline insert»: пользователь не возится с
   * координатами, а получает блок сразу под тем, что редактировал.
   */
  const insertModule = useCallback(
    (module: ModuleDef) => {
      const height = kindOf(module.id) === 'section' ? 200 : 80;
      const y = tree.blocks.reduce((max, b) => Math.max(max, b.y + b.height), 0) + 24;

      const block: Block = {
        id: newBlockId(),
        module: module.id,
        x: 40,
        y,
        width: module.category === 'structure' ? tree.width - 80 : 320,
        height,
        label: module.name,
      };

      history.commit({ ...tree, blocks: [...tree.blocks, block] });
      setSelectedId(block.id);
      markDirty();
    },
    [history, tree, markDirty],
  );

  async function handleSave() {
    // Клиентская проверка дублирует серверную, но даёт мгновенный ответ:
    // не нужно ждать round-trip, чтобы узнать про опечатку в модуле.
    const problem = validateTree(tree);
    if (problem) {
      setSaveError(`Дерево не прошло проверку: ${problem}`);
      setSaveState('error');
      return;
    }

    setSaveState('saving');
    setSaveError(null);
    try {
      const saved = await api.saveProject(
        PROJECT_ID,
        'Интернет-магазин «Цветы»',
        tree,
      );
      // Ответ сервера становится текущим состоянием без записи
      // в историю: это та же правка, уже сохранённая.
      history.reset(saved.tree);
      dirtyRef.current = false;
      setSaveState('saved');
    } catch (e) {
      setSaveError(
        e instanceof ApiError ? `Не сохранено: ${e.message}` : 'Не сохранено: сеть недоступна',
      );
      setSaveState('error');
    }
  }

  /**
   * Горячие клавиши — основа интерфейса, а не бонус (см.
   * docs/UI-DECISIONS.md, раздел 6).
   *
   * Проверка поля ввода обязательна: Ctrl+Z в текстовом поле должен
   * отменять правку текста, а не движение блока на холсте.
   */
  useEffect(() => {
    const isField = (target: EventTarget | null): boolean => {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
    };

    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();

      if (mod && key === 's') {
        e.preventDefault();
        void handleSave();
        return;
      }

      if (isField(e.target)) return;

      if (mod && key === 'z') {
        e.preventDefault();
        if (e.shiftKey) history.redo();
        else history.undo();
        return;
      }
      if (mod && key === 'y') {
        e.preventDefault();
        history.redo();
        return;
      }
      if (mod && key === 'd') {
        e.preventDefault();
        duplicateSelected();
        return;
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (!selectedId) return;
        e.preventDefault();
        deleteSelected();
        return;
      }
      // Инструменты переключаются буквами — как в Figma и Sketch.
      const byKey: Record<string, string> = { v: 'select', h: 'hand', l: 'layers', m: 'modules', t: 'text', i: 'image', d: 'data', f: 'flow' };
      if (!mod && !e.altKey && byKey[key]) {
        setTool(byKey[key]);
      }
    };

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [history, selectedId, duplicateSelected, deleteSelected]);

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
          <button
            type="button"
            className="btn btn--ghost"
            onClick={history.undo}
            disabled={!history.canUndo}
            aria-label="Отменить"
            title="Отменить (Ctrl+Z)"
          >
            <Icon name="undo" />
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={history.redo}
            disabled={!history.canRedo}
            aria-label="Повторить"
            title="Повторить (Ctrl+Shift+Z)"
          >
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
        <main
          className="canvas"
          aria-label="Холст редактора"
          aria-busy={loading}
          // Состояние в data-атрибутах: используется автопроверкой
          // отрисовки (tools/screenshot-editor.mjs), которая не может
          // заглянуть внутрь Konva.
          data-blocks={tree.blocks.length}
          data-selected={selectedId ?? ''}
        >
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

        {/* Панель свойств выбранного блока. Правило «3 клика»:
            выделить блок и поменять свойство. */}
        <aside
          className="props-panel"
          style={{ zIndex: 'var(--layer-drawer)' }}
          data-selected={selectedId ?? ''}
        >
          <PropertiesPanel
            block={selected}
            content={selected?.content ?? ''}
            onPatch={applyPatch}
            onDuplicate={duplicateSelected}
            onDelete={deleteSelected}
            onCopyStyle={copyStyle}
            canPasteStyle={copiedStyle !== null}
            onPasteStyle={pasteStyle}
          />
        </aside>

        {/* Палитра модулей V7. Открывается инструментом «Модули»,
            но панель присутствует в разметке всегда: иначе её появление
            сдвигало бы холст. */}
        <aside
          className={`modules-panel ${tool === 'modules' ? 'is-open' : ''}`}
          style={{ zIndex: 'var(--layer-drawer)' }}
          aria-hidden={tool !== 'modules'}
        >
          <ModulePalette
            modules={modules}
            categories={MODULE_CATEGORIES}
            activeCategory={category}
            onCategoryChange={setCategory}
            onPick={insertModule}
            onOpenFullCatalog={() => setTool('modules')}
            loading={modulesLoading}
          />
        </aside>

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
