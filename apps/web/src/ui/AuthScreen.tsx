/**
 * Экран входа и регистрации (ТЗ п.7.3, п.7.7, п.9.1).
 *
 * Решения, которые видны только в коде:
 *
 * 1. Один экран на два действия. Отдельные страницы «вход» и
 *    «регистрация» заставляли бы держать два маршрута и возвращаться
 *    назад с потерей введённого; здесь переключение простое и не
 *    теряет поля.
 *
 * 2. Поле согласия на обработку персональных данных нельзя
 *    спрятать. Без него регистрация не проходит (152-ФЗ), и это
 *    требование сервера, а не формальность интерфейса.
 *
 * 3. Ошибка входа показывается текстом, а не кодом. Пять неудач под
 *   ряд — это нормальная забывчивость пароля, и показ «429» там, где
 *    человек ошибся в раскладке, выглядит как поломка.
 */

import { useState } from 'react';
import { ApiError, api, type LoginResult, type UserProfile } from './api';
import { clearTokens, hasSession } from './api';

type Mode = 'login' | 'register';

export function AuthScreen({
  onSignedIn,
}: {
  /**
   * Передаётся профиль, а не пустой сигнал: иначе приложению пришлось
   * бы сразу после входа повторно спрашивать /api/auth/me/, и лишний
   * запрос отдавал бы возможность выиграть гонку с отзывом токена.
   */
  onSignedIn: (user: UserProfile) => void;
}) {
  const [mode, setMode] = useState<Mode>('login');
  const [login, setLogin] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      if (mode === 'login') {
        const result: LoginResult = await api.login(login.trim(), password);
        onSignedIn(result.user);
      } else {
        await api.register({
          username: username.trim(),
          email: email.trim(),
          password,
          consent_pdn: consent,
        });
        // Сразу вход: подтверждение email появится вместе с этапом 8,
        // а сейчас регистрация была бы тупиком — зарегистрировался
        // и не смог войти.
        const result = await api.login(username.trim(), password);
        onSignedIn(result.user);
      }
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <form className="auth__card" onSubmit={submit} noValidate>
        <div className="auth__brand">
          <span className="auth__mark" aria-hidden="true" />
          <h1>AuraBuilder</h1>
        </div>

        <div className="auth__tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            className={mode === 'login' ? 'auth__tab is-active' : 'auth__tab'}
            onClick={() => {
              setMode('login');
              setError(null);
            }}
          >
            Вход
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={mode === 'register' ? 'auth__tab is-active' : 'auth__tab'}
            onClick={() => {
              setMode('register');
              setError(null);
            }}
          >
            Регистрация
          </button>
        </div>

        {mode === 'login' ? (
          <label className="auth__field">
            <span className="auth__label">Логин или email</span>
            <input
              className="auth__input"
              name="login"
              autoComplete="username"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              required
            />
          </label>
        ) : (
          <>
            <label className="auth__field">
              <span className="auth__label">Логин</span>
              <input
                className="auth__input"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </label>
            <label className="auth__field">
              <span className="auth__label">Email</span>
              <input
                className="auth__input"
                name="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
          </>
        )}

        <label className="auth__field">
          <span className="auth__label">Пароль</span>
          <input
            className="auth__input"
            name="password"
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            minLength={mode === 'register' ? 12 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {mode === 'register' ? (
            <span className="auth__hint">Не менее 12 символов</span>
          ) : null}
        </label>

        {mode === 'register' ? (
          <label className="auth__consent">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <span>
              Согласен на обработку персональных данных: имя, email и данные о входе
              хранятся для работы аккаунта и уведомлений о безопасности
            </span>
          </label>
        ) : null}

        {error ? (
          <p className="auth__error" role="alert">
            {error}
          </p>
        ) : null}

        <button className="auth__submit" type="submit" disabled={busy}>
          {busy ? 'Подождите…' : mode === 'login' ? 'Войти' : 'Создать аккаунт'}
        </button>
      </form>
    </main>
  );
}

/**
 * Текст ошибки для человека.
 *
 * Коды вроде «429» или «400» пользователю ничего не объясняют, а у
 * сервера этот код нужен для программиста. Сообщение сервера
 * показывается как есть: «Логин уже занят» полезнее обезличенного
 * «Проверьте логин и пароль».
 */
function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Не удалось связаться с сервером.';
  if (error.status === 429) {
    return 'Слишком много попыток. Подождите 10 минут и повторите.';
  }
  // Если сервер вернул осмысленный текст, а не код ответа, —
  // показываем его: он уже сформулирован для пользователя.
  if (error.message && !/^\d+$/.test(error.message)) return error.message;
  if (error.status === 401 || error.status === 400) {
    return 'Проверьте логин и пароль.';
  }
  return `Ошибка ${error.status}. Попробуйте ещё раз.`;
}

/**
 * Нужен ли экран входа прямо сейчас.
 *
 * Вынесено отдельно, чтобы вызывающая сторона не занималась
 * разбором localStorage: это единственное место, где известно,
 * где лежат токены.
 */
export function requiresAuth(): boolean {
  return !hasSession();
}

/** Сброс сессии при истечении токенов. */
export function resetSession(): void {
  clearTokens();
}