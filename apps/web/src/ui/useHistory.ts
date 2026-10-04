/**
 * История изменений дерева страницы — undo/redo.
 *
 * ТЗ п.4.2 и UX-правило «3 клика»: отмена действия должна быть на
 * Ctrl+Z, а не где-то в меню. Кнопки «Отменить» и «Повторить» в
 * верхней панели до этого были без обработчиков — то есть обещали
 * отмену, которой не было.
 *
 * Хранится стек снимков дерева, а не список операций. Для дерева из
 * сотен блоков это дешевле обратных патчей, а история ограничена
 * 50 шагами: глубокая отмена «назад на час» не нужна, зато память
 * не растёт незаметно.
 *
 * Перетаскивание блока даёт одну запись на весь жест, а не на каждый
 * кадр: иначе Ctrl+Z откатывал бы доли пикселя.
 */

import { useCallback, useMemo, useState } from 'react';
import type { PageTree } from './project';

/** Глубина истории. 50 шагов достаточно для рабочей сессии. */
const MAX_HISTORY = 50;

/**
 * Значение, стек «назад», стек «вперёд» и последнее сохранённое
 * состояние хранятся одним объектом: раздельные useState допускали бы
 * рассинхрон между ними при последовательных обновлениях в одном
 * обработчике.
 */
interface HistoryState<T> {
  value: T;
  past: T[];
  future: T[];
  /**
   * Состояние, которое последний раз ушло на сервер.
   *
   * Сравнение с ним, а не отдельный флаг, определяет наличие
   * несохранённых изменений: флаг пришлось бы ставить и снимать в
   * каждом обработчике редактора, и один забытый вызов оставлял бы
   * панель «Не сохранено» навсегда.
   */
  baseline: T;
}

export interface History<T> {
  /** Текущее состояние. */
  value: T;
  /** Можно ли отменить / повторить. */
  canUndo: boolean;
  canRedo: boolean;
  /** Есть ли изменения поверх последнего сохранённого состояния. */
  dirty: boolean;
  /** Фиксирует новое состояние. */
  commit: (next: T) => void;
  /**
   * Заменяет состояние без записи в историю (загрузка с сервера).
   * Отменять после неё нечего, поэтому стеки очищаются.
   */
  reset: (value: T) => void;
  /**
   * Помечает текущее состояние сохранённым, не трогая историю.
   *
   * Вызывается после автосохранения. Раньше здесь был полный сброс
   * истории, и Ctrl+Z переставал работать через секунду после правки:
   * автосохранение затирало стек «назад». Пользователь терял отмену
   * именно в тот момент, когда она становилась нужнее всего, — после
   * паузы в работе.
   */
  markSaved: (value: T) => void;
  undo: () => void;
  redo: () => void;
}

export function useHistory<T>(initial: T): History<T> {
  const [state, setState] = useState<HistoryState<T>>({
    value: initial,
    past: [],
    future: [],
    baseline: initial,
  });

  const commit = useCallback((next: T) => {
    // Вложенные setState (setPast внутри setValue) небезопасны: при
    // быстрых действиях подряд обновления перетирают друг друга,
    // потому что читают устаревший prev. Поэтому снимки и значение
    // хранятся в одном состоянии и меняются атомарно.
    setState((prev) => {
      if (Object.is(prev.value, next)) return prev;
      const merged = [...prev.past, prev.value];
      return {
        value: next,
        past: merged.length > MAX_HISTORY ? merged.slice(-MAX_HISTORY) : merged,
        // Новое действие отменяет ветку «вперёд».
        future: [],
        baseline: prev.baseline,
      };
    });
  }, []);

  const reset = useCallback((next: T) => {
    setState({ value: next, past: [], future: [], baseline: next });
  }, []);

  const markSaved = useCallback((next: T) => {
    setState((prev) => ({ ...prev, value: next, baseline: next }));
  }, []);

  const undo = useCallback(() => {
    setState((prev) => {
      if (prev.past.length === 0) return prev;
      // noUncheckedIndexedAccess не сужает тип по проверке длины,
      // поэтому последний элемент достаётся явно.
      const previous = prev.past[prev.past.length - 1] as T;
      return {
        value: previous,
        past: prev.past.slice(0, -1),
        future: [prev.value, ...prev.future],
        baseline: prev.baseline,
      };
    });
  }, []);

  const redo = useCallback(() => {
    setState((prev) => {
      if (prev.future.length === 0) return prev;
      const next = prev.future[0] as T;
      return {
        value: next,
        past: [...prev.past, prev.value],
        future: prev.future.slice(1),
        baseline: prev.baseline,
      };
    });
  }, []);

  return useMemo(
    () => ({
      value: state.value,
      canUndo: state.past.length > 0,
      canRedo: state.future.length > 0,
      dirty: !Object.is(state.value, state.baseline),
      commit,
      reset,
      markSaved,
      undo,
      redo,
    }),
    [state, commit, reset, markSaved, undo, redo],
  );
}

/** Тип хука для дерева — используется в редакторе. */
export type TreeHistory = History<PageTree>;