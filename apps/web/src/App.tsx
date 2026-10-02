import { useTheme } from './ui/useTheme';
import { EditorCanvas } from './ui/EditorCanvas';
import { Icon } from './ui/icons';

export function App() {
  const { theme, toggle } = useTheme();

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
      <EditorCanvas />
    </>
  );
}
