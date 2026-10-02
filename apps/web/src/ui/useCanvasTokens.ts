/**
 * Чтение значений токенов для Konva.
 *
 * Konva рисует в <canvas> и разбирает цвета собственным парсером — CSS
 * переменные вида var(--canvas) она не понимает и подставляет чёрный.
 * Поэтому значения токенов читаются через getComputedStyle и передаются
 * в Konma уже готовыми строками.
 *
 * Перечитывание происходит при смене темы: атрибут data-theme на <html>
 * меняется, а computed styles — нет.
 */

import { useEffect, useState } from 'react';

/** Токены, которые нужны холсту. Полный набор — в tokens.css. */
export interface CanvasTokens {
  canvas: string;
  panel: string;
  panelSunken: string;
  accentSurfaceSubtle: string;
  border: string;
  selectionBorder: string;
  textSecondary: string;
  textDisabled: string;
  guideLine: string;
}

const VARS: Record<keyof CanvasTokens, string> = {
  canvas: '--canvas',
  panel: '--panel',
  panelSunken: '--panelSunken',
  accentSurfaceSubtle: '--accentSurfaceSubtle',
  border: '--border',
  selectionBorder: '--selectionBorder',
  textSecondary: '--textSecondary',
  textDisabled: '--textDisabled',
  guideLine: '--guideLine',
};

function readTokens(): CanvasTokens {
  const styles = getComputedStyle(document.documentElement);
  const out = {} as CanvasTokens;
  for (const [key, cssVar] of Object.entries(VARS) as [keyof CanvasTokens, string][]) {
    // getPropertyValue отдаёт строку с пробелами — её нужно убрать,
    // иначе Konva не разберёт цвет.
    out[key] = styles.getPropertyValue(cssVar).trim();
  }
  return out;
}

export function useCanvasTokens(): CanvasTokens {
  const [tokens, setTokens] = useState<CanvasTokens>(readTokens);

  useEffect(() => {
    const apply = () => setTokens(readTokens());
    apply();

    // Смена темы не меняет сам computed styles на том же элементе,
    // поэтому подписываемся на мутацию атрибута data-theme.
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });

    return () => observer.disconnect();
  }, []);

  return tokens;
}
