/**
 * Защита от белого экрана.
 *
 * Без него ошибка в любом компоненте размонтирует всё дерево React, и
 * человек видит пустую страницу без объяснения. Для конструктора это
 * особенно дорого: выглядит как «платформа умерла», хотя данные на
 * сервере целы.
 *
 * Класс, а не функция: перехват ошибок рендера React умеет только в
 * componentDidCatch/getDerivedStateFromError.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Ошибка интерфейса:', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (error === null) return this.props.children;
    return (
      <div
        role="alert"
        style={{
          maxWidth: '42rem',
          margin: '4rem auto',
          padding: '1.5rem',
          fontFamily: 'system-ui, sans-serif',
          lineHeight: 1.5,
        }}
      >
        <h1 style={{ fontSize: '1.4rem' }}>Интерфейс остановился</h1>
        <p>
          Данные проекта не пострадали: последнее сохранение осталось на
          сервере. Перезагрузите страницу — редактор откроется с него.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{ padding: '0.5rem 1rem', cursor: 'pointer' }}
        >
          Перезагрузить
        </button>
        <details style={{ marginTop: '1rem' }}>
          <summary style={{ cursor: 'pointer' }}>Подробности для поддержки</summary>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
              fontSize: '0.85rem',
            }}
          >
            {error.message}
          </pre>
        </details>
      </div>
    );
  }
}
