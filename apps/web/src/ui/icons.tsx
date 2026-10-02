/**
 * Собственный набор иконок AuraBuilder.
 *
 * ТЗ п.5.3 требует векторный набор, отрисованный с нуля, и запрещает
 * emoji в интерфейсе: в 13 шаблонах иконки были emoji в тексте, что
 * ломает размеры, цвет и доступность.
 *
 * Сетка 24×24, обводка currentColor толщиной 1.75, скруглённые концы.
 * Все пути используют относительные координаты, иконка наследует цвет
 * от родителя — одна иконка работает в обеих темах.
 */

import type { SVGProps } from 'react';

export type IconName =
  | 'cursor'
  | 'hand'
  | 'layers'
  | 'box'
  | 'type'
  | 'image'
  | 'data'
  | 'flow'
  | 'settings'
  | 'history'
  | 'undo'
  | 'redo'
  | 'eye'
  | 'code'
  | 'grid'
  | 'chevronDown'
  | 'chevronRight'
  | 'close'
  | 'check'
  | 'plus'
  | 'minus'
  | 'search'
  | 'sun'
  | 'moon'
  | 'rocket'
  | 'download'
  | 'trash'
  | 'duplicate'
  | 'alignLeft'
  | 'alignCenter'
  | 'alignRight';

const PATHS: Record<IconName, string> = {
  cursor: 'M5 3l14 8-6 1.5L10 19 5 3z',
  hand: 'M9 11V5.5a1.5 1.5 0 013 0V11m0-1.5a1.5 1.5 0 013 0V12m0-1a1.5 1.5 0 013 0v4a6 6 0 01-6 6h-1a6 6 0 01-6-6v-2a1.5 1.5 0 013 0',
  layers: 'M12 3l9 5-9 5-9-5 9-5zm9 9l-9 5-9-5m18 4.5l-9 5-9-5',
  box: 'M4 7l8-4 8 4v10l-8 4-8-4V7zm0 0l8 4m0 0l8-4m-8 4v10',
  type: 'M5 6V5h14v1M12 5v14M9 19h6',
  image: 'M4 5h16v14H4V5zm2 10l4-4 3 3 2-2 3 3M9 9.5a1 1 0 11-2 0 1 1 0 012 0z',
  data: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6m-16 6c0 1.7 3.6 3 8 3s8-1.3 8-3',
  flow: 'M6 6h4v4H6V6zm8 8h4v4h-4v-4zM10 8h4a2 2 0 012 2v2',
  settings:
    'M12 15a3 3 0 100-6 3 3 0 000 6zm8-3a8 8 0 01-.1 1.2l2 1.6-2 3.4-2.4-1a8 8 0 01-2 1.2l-.4 2.6h-4l-.4-2.6a8 8 0 01-2-1.2l-2.4 1-2-3.4 2-1.6a8 8 0 010-2.4l-2-1.6 2-3.4 2.4 1a8 8 0 012-1.2L10 3h4l.4 2.6a8 8 0 012 1.2l2.4-1 2 3.4-2 1.6c.1.4.1.8.1 1.2z',
  history: 'M4 12a8 8 0 108-8 8 8 0 00-6.9 4M4 4v4h4m4 0v4l3 2',
  undo: 'M9 14L4 9l5-5m-5 5h9a5 5 0 010 10h-3',
  redo: 'M15 14l5-5-5-5m5 5h-9a5 5 0 000 10h3',
  eye: 'M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6zm9.5 2.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z',
  code: 'M8.5 8L4 12l4.5 4M15.5 8l4.5 4-4.5 4M13.5 5l-3 14',
  grid: 'M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z',
  chevronDown: 'M6 9.5l6 6 6-6',
  chevronRight: 'M9.5 6l6 6-6 6',
  close: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  search: 'M11 18a7 7 0 100-14 7 7 0 000 14zm5.5-1.5L21 21',
  sun: 'M12 16a4 4 0 100-8 4 4 0 000 8zM12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8',
  moon: 'M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z',
  rocket: 'M12 3c3.5 2 5.5 5.5 5.5 9.5L15 15H9l-2.5-2.5C6.5 8.5 8.5 5 12 3zM9.5 12.5l-3 5 5-2.5M14.5 12.5l3 5-5-2.5M12 15v3',
  download: 'M12 4v10m0 0l-4-4m4 4l4-4M5 19h14',
  trash: 'M5 7h14M9 7V5h6v2m-8 0l1 12h8l1-12M10 11v5M14 11v5',
  duplicate: 'M8 8h11v11H8V8zM5 16V5h11',
  alignLeft: 'M4 6h16M4 12h9M4 18h13',
  alignCenter: 'M4 6h16M7 12h10M6 18h12',
  alignRight: 'M4 6h16M11 12h9M7 18h13',
};

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
  /** Размер в пикселях. По умолчанию 20 — комфортно для панели 44px. */
  size?: number;
  /**
   * Иконка, оформленная только обводкой. Иконки, которые несут смысл
   * самостоятельно, лучше рисовать контуром; default заполненных нет.
   */
  title?: string;
}

export function Icon({ name, size = 20, title, ...rest }: IconProps) {
  const d = PATHS[name];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      <path d={d} />
    </svg>
  );
}

export const iconNames = Object.keys(PATHS) as IconName[];
