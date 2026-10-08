import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import { generateTokensCss, paletteValues } from '../../packages/tokens/css.mjs';

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
  // Значения палитры по темам нужны JavaScript'у: библиотека компонентов
  // проверяет контраст выбранных цветов, а страницу можно переключить в
  // тёмную тему в любой момент. Из CSS в браузере достаются только
  // переменные текущей темы, а проверять надо обе: сервер отвергает
  // сочетание, которое нечитаемо хоть в одной.
  const PALETTE_ID = 'virtual:aurabuilder-palette';
  const PALETTE_RESOLVED = `\0${PALETTE_ID}`;

  return {
    name: 'aurabuilder-tokens',
    resolveId(id) {
      if (id === VIRTUAL_ID || id === '@tokens') return RESOLVED;
      if (id === PALETTE_ID) return PALETTE_RESOLVED;
      return null;
    },
    load(id) {
      // Следим за palette.json: правка палитры перезагружает страницу
      if (id === RESOLVED || id === PALETTE_RESOLVED) {
        this.addWatchFile(fileURLToPath(new URL('../../docs/palette.json', import.meta.url)));
      }
      if (id === RESOLVED) return generateTokensCss();
      if (id === PALETTE_RESOLVED) return `export default ${JSON.stringify(paletteValues())};`;
      return null;
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
    /*
     * Прокси на Control Plane — только для режима разработки.
     *
     * Без него фронт на 5173 ходил бы на API напрямую и запросы
     * падали бы по CORS: в проекте его нет сознательно, ставить
     * django-cors-headers ради dev-режима значило бы расширить
     * поверхность атаки на проде. Dev-сервер повторяет то, что делает
     * nginx: отдаёт статику сам, /api проксирует на API.
     *
     * Адрес задаётся переменной окружения, потому что порт API
     * отличается от боевого и меняется вместе с .env.
     */
    proxy: {
      '/api': {
        target: process.env.API_TARGET ?? 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },

  build: {
    target: 'es2022',
    sourcemap: true,
    // ТЗ п.1.3: LCP < 1.5 с.
    //
    // Konva (около 100 КБ gzip) НЕ должен попадать в критический путь:
    // он нужен только холсту, а панель инструментов рисуется без него.
    // Поэтому чанк с Konva не получает modulepreload — иначе браузер
    // качает его параллельно React и первый экран откладывается.
    // Загрузка холста идёт через React.lazy после появления каркаса.
    // Konva намеренно НЕ выносится в отдельный manualChunks-чанк.
    // Такой чанк Vite помечает modulepreload, и браузер начинает качать
    // 100 КБ gzip канваса параллельно с React: первый экран откладывается
    // (замер: LCP вырос с 1408 до 1592 мс при бюджете 1500).
    // Без ручного чанка Konva уезжает внутрь ленивого чанка холста,
    // который React.lazy подгружает уже после отрисовки каркаса.
    modulePreload: {
      // Канвас не в критическом пути — фильтруем его зависимости.
      resolveDependencies(filename, deps) {
        if (filename.includes('Canvas')) {
          return deps.filter((d) => !/node_modules[\\/](konva|react-konva)/.test(d));
        }
        return deps;
      },
    },
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('react-dom') || /node_modules[\\/]react[\\/]/.test(id)) return 'react';
          }
          return undefined;
        },
      },
    },
  },
});
