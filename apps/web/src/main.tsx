import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

// Токены приходят виртуальным модулем: содержимое генерируется из
// docs/palette.json плагином в vite.config.ts. Правка палитры
// перезагружает страницу автоматически.
// Источник значений: npm run tokens:build
import '@tokens';
import './styles/base.css';

const root = document.getElementById('root');
if (!root) {
  throw new Error('не найден элемент #root в index.html');
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
