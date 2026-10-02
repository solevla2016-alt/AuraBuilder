import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import { generateTokensCss } from '../../packages/tokens/css.mjs';

/**
 * Токены отдаются виртуальным модулем, а не файлом из packages/.
 *
 * Причина: путь к репозиторию содержит кириллицу («Пользователь»), и Vite
 * не декодирует такие пути в dev-режиме — вместо CSS отдаётся index.html.
 * Виртуальный модуль снимает зависимость от файловой системы: содержимое
 * генерируется из docs/palette.json прямо здесь.
 */
function tokensPlugin(): Plugin {
  const VIRTUAL_ID = 'virtual:aurabuilder-tokens';
  // Расширение .css обязательно: без него сборщик пытается разобрать
  // содержимое как JavaScript и падает на первом же «:root {».
  const RESOLVED = `\0${VIRTUAL_ID}.css`;

  return {
    name: 'aurabuilder-tokens',
    resolveId(id) {
      if (id === VIRTUAL_ID || id === '@tokens') return RESOLVED;
      return null;
    },
    load(id) {
      if (id !== RESOLVED) return null;
      // Следим за palette.json: правка палитры перезагружает страницу
      this.addWatchFile(fileURLToPath(new URL('../../docs/palette.json', import.meta.url)));
      return generateTokensCss();
    },
  };
}

export default defineConfig({
  plugins: [tokensPlugin(), react()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    port: 5173,
    strictPort: false,
  },

  build: {
    target: 'es2022',
    sourcemap: true,
    // ТЗ п.1.3: LCP < 1.5 с. Konva выносится в отдельный чанк,
    // чтобы не попадать в критический путь первого экрана.
    //
    // Rolldown (движок Vite 8) принимает здесь только функцию:
    // объектная форма manualChunks не поддерживается.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('konva')) return 'konva';
            if (id.includes('react')) return 'react';
          }
          return undefined;
        },
      },
    },
  },
});
