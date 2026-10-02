/**
 * Переключатель темы. Тема хранится в data-theme на <html>, значения
 * берутся из CSS-переменных (packages/tokens/dist/tokens.css).
 *
 * Выбор запоминается в localStorage. Системная тема учитывается, пока
 * пользователь не выбрал вручную — иначе переключатель «сбрасывался бы»
 * при перезагрузке у тех, кто привык к тёмной.
 */

import { useCallback, useEffect, useState } from 'react';

export type ThemeName = 'light' | 'dark';

const STORAGE_KEY = 'aurabuilder.theme';

function systemTheme(): ThemeName {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

function stored(): ThemeName | null {
  if (typeof window === 'undefined') return null;
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === 'light' || v === 'dark' ? v : null;
}

function apply(theme: ThemeName) {
  document.documentElement.setAttribute('data-theme', theme);
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemeName>(() => stored() ?? systemTheme());

  useEffect(() => {
    apply(theme);
  }, [theme]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      // Следуем за системой, только пока пользователь не выбрал сам.
      if (stored() === null) setTheme(mq.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === 'light' ? 'dark' : 'light';
      window.localStorage.setItem(STORAGE_KEY, next);
      return next;
    });
  }, []);

  return { theme, setTheme, toggle };
}
