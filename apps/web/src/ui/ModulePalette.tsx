/**
 * Палитра модулей — вариант V7 «Inline Insert» (docs/UI-DECISIONS.md, 3.2).
 *
 * Инлайновое добавление в позицию курсора — основной путь: не нужно
 * переключаться между холстом и библиотекой. V2 (Modal Grid) остаётся
 * для случая, когда пользователь не знает, что ищет.
 *
 * Модули приходят из Control Plane; локальная копия реестра
 * (moduleRegistry.ts) используется, пока запрос не прошёл, и для типов.
 */

import { useMemo, useState } from 'react';
import { Icon } from './icons';
import { kindOf } from './moduleRegistry';
import type { ModuleDef } from './moduleRegistry';

export interface ModulePaletteProps {
  modules: ModuleDef[];
  categories: { code: string; id: string; label: string }[];
  activeCategory: string | null;
  onCategoryChange: (id: string | null) => void;
  onPick: (module: ModuleDef) => void;
  onOpenFullCatalog: () => void;
  loading: boolean;
}

export function ModulePalette({
  modules,
  categories,
  activeCategory,
  onCategoryChange,
  onPick,
  onOpenFullCatalog,
  loading,
}: ModulePaletteProps) {
  const [query, setQuery] = useState('');

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return modules.filter((m) => {
      if (activeCategory && m.category !== activeCategory) return false;
      if (!needle) return true;
      // Ищем по названию и по id: пользователь может знать и то,
      // и другое («герой» или «section.hero»).
      return m.name.toLowerCase().includes(needle) || m.id.toLowerCase().includes(needle);
    });
  }, [modules, activeCategory, query]);

  if (loading) {
    return (
      <div className="modules" role="status">
        <p className="modules__empty">Загрузка каталога модулей…</p>
      </div>
    );
  }

  return (
    <div className="modules">
      <div className="modules__search">
        <Icon name="search" size={16} />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Найти модуль"
          aria-label="Поиск модуля"
        />
      </div>

      <div className="modules__cats" role="group" aria-label="Категории модулей">
        <button
          type="button"
          className={`modules__cat ${activeCategory === null ? 'is-active' : ''}`}
          onClick={() => onCategoryChange(null)}
        >
          Все
        </button>
        {categories.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`modules__cat ${activeCategory === c.id ? 'is-active' : ''}`}
            onClick={() => onCategoryChange(c.id)}
          >
            {c.label}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <p className="modules__empty">Ничего не найдено</p>
      ) : (
        <ul className="modules__list">
          {visible.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                className="modules__item"
                onClick={() => onPick(m)}
                title={`${m.id} · этап ${m.minStage}`}
              >
                <span className={`modules__kind modules__kind--${kindOf(m.id)}`} aria-hidden="true" />
                <span className="modules__text">
                  <b>{m.name}</b>
                  <code>{m.id}</code>
                </span>
                <Icon name="plus" size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <button type="button" className="modules__all" onClick={onOpenFullCatalog}>
        <Icon name="grid" size={16} />
        Весь каталог
        <span className="modules__count">{modules.length}</span>
      </button>
    </div>
  );
}
