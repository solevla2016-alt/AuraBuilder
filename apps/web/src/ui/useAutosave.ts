/**
 * Автосохранение.
 *
 * Пока его не было, работа терялась при закрытии вкладки: сохранять
 * требовалось вручную по Ctrl+S. Для конструктора это недопустимо —
 * страх потерять неделю работы сильнее раздражения от лишнего запроса.
 *
 * Решения, которые неочевидны:
 *
 * 1. Пауза перед сохранением. Запись в поле содержимого создаёт
 *    изменение на каждый символ; сохранять на каждый символ значило бы
 *    60 запросов в минуту.
 *
 * 2. Только при наличии изменений. Каждый заход на страницу не должен
 *    портить временную метку «сохранено N назад».
 *
 * 3. Таймер не отменяется в cleanup. Казалось бы, так правильно:
 * *эффект отменил отложенное сохранение, компонент исчез — работать
 *    больше нечему*. На практике StrictMode в dev вызывает cleanup
 *    после второго запуска эффекта, и таймер отменялся уже после
 *    того, как новый был поставлен: сохранение не срабатывало НИКОГДА,
 *    а панель вечно показывала «Есть несохранённые изменения».
 *    Проверка воспроизводит это в tools/screenshot-editor.mjs.
 *    Поэтому отложенное сохранение переустанавливается в начале
 *    эффекта, а не отменяется в его конце.
 *
 * 4. Отмена меняет сохранённость. Ctrl+Z возвращает дерево к
 *    сохранённому состоянию — сохранять после отмены незачем.
 *    Определяет это сам useHistory: сравнение с последним
 *    сохранённым состоянием, а не флаг в редакторе.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';

/** Пауза перед автосохранением, мс. */
const DEBOUNCE_MS = 1200;

export interface AutosaveOptions {
  /** Сохранить. Бросок исключения переводит состояние в error. */
  save: () => Promise<void>;
  /** Есть ли несохранённые изменения. */
  dirty: boolean;
  /** Включено ли автосохранение. */
  enabled?: boolean;
}

export interface Autosave {
  state: SaveState;
  error: string | null;
  /** Время последнего успешного сохранения, мс от эпохи. */
  savedAt: number | null;
  /** Человеческая подпись «сохранено N назад». */
  label: string;
  /** Принудительное сохранение. */
  saveNow: () => Promise<void>;
}

/** «сейчас», «12 секунд назад», «4 минуты назад». */
export function formatAgo(savedAt: number | null, now: number): string {
  if (savedAt === null) return 'Ещё не сохранялось';
  const seconds = Math.max(0, Math.round((now - savedAt) / 1000));
  if (seconds < 5) return 'Сохранено только что';
  if (seconds < 60) return `Сохранено ${seconds} секунд назад`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `Сохранено ${minutes} ${plural(minutes, 'минуту', 'минуты', 'минут')} назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Сохранено ${hours} ${plural(hours, 'час', 'часа', 'часов')} назад`;
  const days = Math.round(hours / 24);
  return `Сохранено ${days} ${plural(days, 'день', 'дня', 'дней')} назад`;
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

export function useAutosave({ save, dirty, enabled = true }: AutosaveOptions): Autosave {
  const [state, setState] = useState<SaveState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);
  // Функция сохранения меняется каждый рендер; храним её в ref,
  // иначе useEffect ниже перезапускался бы на каждый рендер.
  const saveRef = useRef(save);
  saveRef.current = save;
  // Тот же приём для признака «есть что сохранять»: обработчикам
  // ухода со страницы нужен актуальный ответ, а не тот, что был
  // на момент последнего рендера.
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  const run = useCallback(async () => {
    // Параллельных сохранений быть не должно: два одновременных PUT
    // могли бы записать разные версии дерева в неопределённом порядке.
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setState('saving');
    setError(null);
    try {
      await saveRef.current();
      setSavedAt(Date.now());
      setState('saved');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Неизвестная ошибка');
      setState('error');
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  const saveNow = useCallback(async () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    await run();
  }, [run]);

  // Debounce на каждое новое изменение. Cleanup здесь намеренно
  // отсутствует — см. пункт 3 в шапке модуля.
  useEffect(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (!enabled || !dirty) return;
    setState((prev) => (prev === 'saving' ? prev : 'dirty'));
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      void run();
    }, DEBOUNCE_MS);
  }, [dirty, enabled, run]);

  // Уход со страницы: пауза перед сохранением не должна стоить работы.
  // pagehide надёжнее beforeunload (его нельзя отменить), а
  // visibilitychange ловит сворачивание вкладки и уход на другую.
  useEffect(() => {
    const flush = () => {
      if (!dirtyRef.current) return;
      void saveNow();
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flush();
    };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('pagehide', flush);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [saveNow]);

  // Таймер для подписи «N назад»: раз в 10 секунд достаточно,
  // чаще — просто мигание цифр.
  useEffect(() => {
    if (state !== 'saved') return;
    const id = window.setInterval(() => setNow(Date.now()), 10000);
    return () => window.clearInterval(id);
  }, [state]);

  const label =
    state === 'saving'
      ? 'Сохраняем…'
      : state === 'error'
        ? 'Не сохранено'
        : state === 'dirty'
          ? 'Есть несохранённые изменения'
          : formatAgo(savedAt, now);

  return { state, error, savedAt, label, saveNow };
}