import { useCallback, useEffect, useState } from 'react';
import { useTheme } from './ui/useTheme';
import { EditorCanvas } from './ui/EditorCanvas';
import { AuthScreen, requiresAuth } from './ui/AuthScreen';
import { ProjectListScreen } from './ui/ProjectListScreen';
import { DataScreen } from './ui/DataScreen';
import { Icon } from './ui/icons';
import { api, clearTokens, onSessionExpired, type UserProfile } from './ui/api';
import type { Project } from './ui/project';

/**
 * Три состояния приложения, а не маршрутизация через URL.
 *
 * Навигация по хешу съела бы строку, но дала бы один лишний слой
 * состояния: экран списка и редактор — это не страницы сайта, а шаги
 * одного сценария. По той же причине проект не кладётся в адресную
 * строку: ссылку на редактор всё равно нельзя показать другому
 * человеку, пока нет «Открыть по ссылке» (этап командной работы).
 */
type Screen =
  | { name: 'dashboard' }
  | { name: 'editor'; project: Project }
  | { name: 'data'; project: Project };

export function App() {
  const { theme, toggle } = useTheme();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: 'dashboard' });
  const [booting, setBooting] = useState(true);

  // Профиль запрашивается один раз при старте: без него неизвестно,
  // показывать экран входа или список проектов.
  useEffect(() => {
    if (!requiresAuth()) {
      api
        .me()
        .then(setUser)
        .catch(() => {
          // Токен есть, но сервер его не признал: чистим и просим войти.
          clearTokens();
          setUser(null);
        })
        .finally(() => setBooting(false));
    } else {
      setBooting(false);
    }
  }, []);

  // Истёкший refresh выкидывает на экран входа. Без этого редактор
  // остался бы открытым, а автосохранение тихо падало бы в 401.
  useEffect(
    () =>
      onSessionExpired(() => {
        setUser(null);
        setScreen({ name: 'dashboard' });
      }),
    [],
  );

  const signOut = useCallback(() => {
    void api.logout().finally(() => {
      setUser(null);
      setScreen({ name: 'dashboard' });
    });
  }, []);

  return (
    <>
      <button
        type="button"
        className="theme-toggle"
        onClick={toggle}
        aria-label={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'}
        title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}
      >
        <Icon name={theme === 'light' ? 'moon' : 'sun'} />
      </button>

      {booting ? null : user === null ? (
        <AuthScreen onSignedIn={(profile) => setUser(profile)} />
      ) : screen.name === 'dashboard' ? (
        <ProjectListScreen
          user={user}
          onOpen={(project) => setScreen({ name: 'editor', project })}
          onSignOut={signOut}
        />
      ) : screen.name === 'data' ? (
        <DataScreen
          projectId={screen.project.id}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : (
        <EditorCanvas
          project={screen.project}
          onBack={() => setScreen({ name: 'dashboard' })}
          onOpenData={() => setScreen({ name: 'data', project: screen.project })}
          onSignOut={signOut}
        />
      )}
    </>
  );
}