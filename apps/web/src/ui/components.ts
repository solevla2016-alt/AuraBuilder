/**
 * Клиент библиотеки компонентов (ТЗ п.3.1).
 *
 * Стиль задаётся один раз на вид компонента и применяется ко всем
 * блокам этого вида. Здесь — только формат и адреса; разбор цвета в
 * значение для Konva живёт в useCanvasTokens, потому что читать токены
 * палитры умеет только браузер.
 */

import palette from 'virtual:aurabuilder-palette';
import { request } from './apiClient';

export type ComponentKind = 'section' | 'text' | 'media';

export interface ComponentTokens {
  /** Имя токена палитры или #RRGGBB. */
  background: string;
  text: string;
  radius: number;
  padding: number;
  weight: number;
  border: number;
}

export interface ComponentStyle {
  kind: ComponentKind;
  tokens: ComponentTokens;
  /** Стиль взят по умолчанию: пользователь его не менял. */
  isDefault: boolean;
  updatedAt: string | null;
}

export interface ResolvedStyle {
  fill: string;
  text: string;
  radius: number;
  padding: number;
  weight: number;
  border: number;
}

export const COMPONENT_LABELS: { kind: ComponentKind; label: string; hint: string }[] = [
  {
    kind: 'section',
    label: 'Секция',
    hint: 'Первый экран, шапка, подвал, блок «О нас». Стиль применяется ко всем секциям сайта.',
  },
  {
    kind: 'text',
    label: 'Текст',
    hint: 'Заголовки и абзацы. Цвет текста и насыщенность берутся отсюда.',
  },
  {
    kind: 'media',
    label: 'Медиа',
    hint: 'Изображения, галереи, видео. Задаёт подложку и рамку вокруг файла.',
  },
];

/**
 * Токены палитры, пригодные как фон или цвет текста.
 *
 * Список взят из палитры проекта: он же уходит в Control Plane, и
 * сервер отвергает всё, чего здесь нет. Расхождение означало бы, что
 * интерфейс предлагает цвет, который сохранить нельзя.
 */
export const COLOR_TOKENS = [
  'canvas',
  'panel',
  'panelRaised',
  'panelSunken',
  'accentSurface',
  'accentSurfaceSubtle',
  'success',
  'warning',
  'danger',
  'info',
] as const;

export const TEXT_TOKENS = [
  'textPrimary',
  'textSecondary',
  'textInverse',
  'accentText',
  'onAccentText',
  'onAccentSurface',
  'success',
  'warning',
  'danger',
  'info',
] as const;

export const COLOR_LABELS: Record<string, string> = {
  canvas: 'Страница',
  panel: 'Панель',
  panelRaised: 'Приподнятая',
  panelSunken: 'Утопленная',
  panelOverlay: 'Наложение',
  appBg: 'Фон приложения',
  textPrimary: 'Основной текст',
  textSecondary: 'Второстепенный',
  textDisabled: 'Неактивный',
  textInverse: 'Инверсный',
  accentSurface: 'Акцент',
  accentSurfaceSubtle: 'Акцент слабый',
  accentSurfaceSunken: 'Акцент утопленный',
  onAccentSurface: 'На акценте',
  onAccentText: 'Текст на акценте',
  success: 'Успех',
  warning: 'Внимание',
  danger: 'Ошибка',
  info: 'Информация',
  selectionBorder: 'Выделение',
};

export const componentsApi = {
  list: (projectId: string) =>
    request<{ styles: ComponentStyle[] }>(`/projects/${projectId}/component-styles/`),

  save: (projectId: string, kind: ComponentKind, tokens: ComponentTokens) =>
    request<ComponentStyle>(`/projects/${projectId}/component-styles/${kind}/`, {
      method: 'PUT',
      body: JSON.stringify({ tokens }),
    }),

  reset: (projectId: string, kind: ComponentKind) =>
    request<void>(`/projects/${projectId}/component-styles/${kind}/`, { method: 'DELETE' }),
};

/** Цвет для Konva: токен палитры читается через CSS-переменную. */
export function colorValue(token: string, fallback: string): string {
  if (/^#[0-9a-f]{6}$/i.test(token)) return token;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(`--${token}`)
    .trim();
  return value || fallback;
}

/**
 * Стиль компонента для отрисовки.
 *
 * Подставляются значения по умолчанию, а не undefined: пропуск цвета
 * означал бы чёрную заливку в Konva и «пустую» страницу у заказчика.
 */
export function resolveStyle(
  kind: ComponentKind,
  styles: Record<ComponentKind, ComponentStyle> | null,
  fallbackFill: string,
  fallbackText: string,
): ResolvedStyle {
  const style = styles?.[kind]?.tokens;
  return {
    fill: style ? colorValue(style.background, fallbackFill) : fallbackFill,
    text: style ? colorValue(style.text, fallbackText) : fallbackText,
    radius: style?.radius ?? 8,
    padding: style?.padding ?? 20,
    weight: style?.weight ?? 400,
    border: style?.border ?? 1,
  };
}

/** Список стилей в виде словаря: холст обращается по виду компонента. */
export function byKind(list: ComponentStyle[]): Record<ComponentKind, ComponentStyle> {
  return {
    section: list.find((s) => s.kind === 'section') as ComponentStyle,
    text: list.find((s) => s.kind === 'text') as ComponentStyle,
    media: list.find((s) => s.kind === 'media') as ComponentStyle,
  };
}

/* --- Контраст в браузере --- */

/*
 * Контраст считается и на клиенте, и на сервере. Сервер — источник
 * истины: палитра пополняется, и проверка обязана быть там. Здесь она
 * нужна, чтобы показать результат до сохранения: пользователь видит
 * «2.1:1 — не читается» вместо отказа после нажатия.
 */

const MIN_CONTRAST = 4.5;

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Контраст двух непрозрачных цветов по WCAG 2.1. */
export function contrastRatio(first: string, second: string): number {
  const parse = (hex: string): [number, number, number] => {
    const value = hex.replace('#', '');
    return [
      parseInt(value.slice(0, 2), 16),
      parseInt(value.slice(2, 4), 16),
      parseInt(value.slice(4, 6), 16),
    ];
  };
  if (!/^#[0-9a-f]{6}$/i.test(first) || !/^#[0-9a-f]{6}$/i.test(second)) return 0;
  const [r1, g1, b1] = parse(first).map(channel) as [number, number, number];
  const [r2, g2, b2] = parse(second).map(channel) as [number, number, number];
  const l1 = 0.2126 * r1 + 0.7152 * g1 + 0.0722 * b1;
  const l2 = 0.2126 * r2 + 0.7152 * g2 + 0.0722 * b2;
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return Math.round(((lighter + 0.05) / (darker + 0.05)) * 100) / 100;
}

/**
 * Контраст токена «текст» на токене «фон» в текущей теме.
 *
 * Считается по теме, которой живёт редактор: полная проверка по обеим
 * темам остаётся на сервере, а здесь достаточно показать, читаемо ли
 * сочетание на глаз.
 */
export function pairContrast(background: string, text: string): number {
  return contrastRatio(colorValue(background, '#FFFFFF'), colorValue(text, '#1A1C1E'));
}

/**
 * Контраст в худшей из тем.
 *
 * Проверка по обеим темам — не перестраховка: сервер отвергает
 * сочетание, нечитаемое хоть в одной из них, а страницу переключают в
 * тёмную тему в любой момент. Считать только по текущей означало бы
 * предлагать пользователю сочетание, которое откажут на сохранении.
 */
export function worstPairContrast(background: string, text: string): number {
  const value = (token: string, theme: Record<string, string>, fallback: string) =>
    /^#[0-9a-f]{6}$/i.test(token) ? token : (theme[token] ?? fallback);
  const ratios = Object.values(palette).map((theme) =>
    contrastRatio(value(text, theme, '#1A1C1E'), value(background, theme, '#FFFFFF')),
  );
  // Ноль, если токен неизвестен палитре: неизвестное не считаем прочитанным.
  return ratios.some((r) => r === 0) ? 0 : Math.min(...ratios);
}

export { MIN_CONTRAST };