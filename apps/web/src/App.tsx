import { useEffect, useState } from 'react';
import { useTheme } from './ui/useTheme';
import { EditorCanvas } from './ui/EditorCanvas';
import { AuthScreen, requiresAuth } from './ui/AuthScreen';
import { Icon } from './ui/icons';
import { onSessionExpired } from './ui/api';

export function App() {
  const { theme, toggle } = useTheme();
  // Проверка идёт один раз при монтировании: токены появляются после
  // входа, и каждый ререндер перечитывать localStorage незачем.
  const [signedIn, setSignedIn] = useState(() => !requiresAuth());

  // Истёкший refresh выкидывает на экран входа. Без этого редактор
  // остался бы открытым, а автосохранение тихо падало бы в 401.
  useEffect(() => onSessionExpired(() => setSignedIn(false)), []);

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
      {signedIn ? (
        <EditorCanvas onSignOut={() => setSignedIn(false)} />
      ) : (
        <AuthScreen onSignedIn={() => setSignedIn(true)} />
      )}
    </>
  );
}