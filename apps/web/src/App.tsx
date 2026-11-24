import { useCallback, useEffect, useState } from 'react';
import { useTheme } from './ui/useTheme';
import { EditorCanvas } from './ui/EditorCanvas';
import { AuthScreen, requiresAuth } from './ui/AuthScreen';
import { ProjectListScreen } from './ui/ProjectListScreen';
import { DataScreen } from './ui/DataScreen';
import { ComponentsScreen } from './ui/ComponentsScreen';
import { VersionsScreen } from './ui/VersionsScreen';
import { PublishScreen } from './ui/PublishScreen';
import { LogicScreen } from './ui/LogicScreen';
import { AnalyticsScreen } from './ui/AnalyticsScreen';
import { TemplatesScreen } from './ui/TemplatesScreen';
import { ReviewScreen } from './ui/ReviewScreen';
import { WebhooksScreen } from './ui/WebhooksScreen';
import { AcademyScreen } from './ui/AcademyScreen';
import { SubscriptionScreen } from './ui/SubscriptionScreen';
import { AssistantScreen } from './ui/AssistantScreen';
import { Icon } from './ui/icons';
import { api, clearTokens, onSessionExpired, type PlatformConfig, type UserProfile } from './ui/api';
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
  | { name: 'data'; project: Project }
  | { name: 'components'; project: Project }
  | { name: 'versions'; project: Project }
  | { name: 'publish'; project: Project }
  | { name: 'logic'; project: Project }
  | { name: 'analytics'; project: Project }
  | { name: 'templates'; project: Project }
  | { name: 'review'; project: Project }
  | { name: 'webhooks'; project: Project }
  | { name: 'assistant'; project: Project }
  | { name: 'academy' }
  | { name: 'subscription' };

export function App() {
  const { theme, toggle } = useTheme();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: 'dashboard' });
  const [booting, setBooting] = useState(true);
  const [config, setConfig] = useState<PlatformConfig | null>(null);

  // Режим сервера нужен экрану входа до появления токена. Ошибка не
  // блокирует вход: если /api/config/ недоступен, показываем облачный
  // вариант — форма, которую сервер отклонит, лучше скрытой формы.
  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

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
        <AuthScreen
          onSignedIn={(profile) => setUser(profile)}
          registrationOpen={config?.registrationOpen ?? true}
        />
      ) : screen.name === 'dashboard' ? (
        <ProjectListScreen
          user={user}
          onOpen={(project) => setScreen({ name: 'editor', project })}
          onOpenAcademy={() => setScreen({ name: 'academy' })}
          onOpenSubscription={() => setScreen({ name: 'subscription' })}
          onSignOut={signOut}
        />
      ) : screen.name === 'academy' ? (
        <AcademyScreen onBack={() => setScreen({ name: 'dashboard' })} />
      ) : screen.name === 'subscription' ? (
        <SubscriptionScreen onBack={() => setScreen({ name: 'dashboard' })} />
      ) : screen.name === 'data' ? (
        <DataScreen
          projectId={screen.project.id}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'versions' ? (
        <VersionsScreen
          projectId={screen.project.id}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'logic' ? (
        <LogicScreen
          projectId={screen.project.id}
          projectName={screen.project.name}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'publish' ? (
        <PublishScreen
          projectId={screen.project.id}
          projectName={screen.project.name}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'analytics' ? (
        <AnalyticsScreen
          projectId={screen.project.id}
          projectName={screen.project.name}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'templates' ? (
        <TemplatesScreen
          projectId={screen.project.id}
          projectName={screen.project.name}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'review' ? (
        <ReviewScreen
          projectId={screen.project.id}
          projectName={screen.project.name}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'webhooks' ? (
        <WebhooksScreen
          projectId={screen.project.id}
          projectName={screen.project.name}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : screen.name === 'assistant' ? (
        <AssistantScreen
          projectId={screen.project.id}
          projectName={screen.project.name}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
          onOpenSubscription={() => setScreen({ name: 'subscription' })}
        />
      ) : screen.name === 'components' ? (
        <ComponentsScreen
          projectId={screen.project.id}
          onBack={() => setScreen({ name: 'editor', project: screen.project })}
        />
      ) : (
        <EditorCanvas
          project={screen.project}
          onBack={() => setScreen({ name: 'dashboard' })}
          onOpenPublish={() => setScreen({ name: 'publish', project: screen.project })}
          onOpenData={() => setScreen({ name: 'data', project: screen.project })}
          onOpenComponents={() => setScreen({ name: 'components', project: screen.project })}
          onOpenVersions={() => setScreen({ name: 'versions', project: screen.project })}
          onOpenLogic={() => setScreen({ name: 'logic', project: screen.project })}
          onOpenAnalytics={() => setScreen({ name: 'analytics', project: screen.project })}
          onOpenTemplates={() => setScreen({ name: 'templates', project: screen.project })}
          onOpenReview={() => setScreen({ name: 'review', project: screen.project })}
          onOpenWebhooks={() => setScreen({ name: 'webhooks', project: screen.project })}
          onOpenAssistant={() => setScreen({ name: 'assistant', project: screen.project })}
          onSignOut={signOut}
        />
      )}
    </>
  );
}