/**
 * Модель дерева страницы — общий контракт между редактором и Control Plane.
 *
 * Формат совпадает с деревом блоков из docs/MODULE-CATALOG.md и должен
 * оставаться стабильным: он уходит в API и в экспорт (ТЗ п.16.2).
 * Поэтому типы описаны явно, а не через any.
 *
 * Идентификатор модуля приходит из реестра (moduleRegistry.ts),
 * который генерируется из того же каталога модулей. Дублировать
 * список модулей здесь нельзя — расхождение проявилось бы только
 * на попытке положить на холст несуществующий блок.
 */

import { MODULE_IDS } from './moduleRegistry';
import type { ModuleKind } from './moduleRegistry';

export type { ModuleKind };

/**
 * Выравнивание содержимого внутри блока.
 */
export type Align = 'left' | 'center' | 'right';

export interface Block {
  /** Идентификатор экземпляра блока на странице, не модуля. */
  id: string;
  /** Идентификатор модуля каталога, например `section.hero`. */
  module: string;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  /** Выравнивание содержимого; по умолчанию left. */
  align?: Align;
  /** Текстовое содержимое. Для блоков данных появится на этапе 3. */
  content?: string;
  /**
   * Схема свойств модуля. Хранит только изменённые значения: всё
   * остальное подставляется из реестра при отрисовке, иначе каждый
   * блок раздувался бы одинаковыми значениями по умолчанию.
   */
  props?: Record<string, string | number | boolean>;
}

export interface PageTree {
  width: number;
  blocks: Block[];
}

export interface Project {
  id: string;
  name: string;
  /** Дерево страницы; обновляется при сохранении. */
  tree: PageTree;
  updatedAt: string;
}

const MAX_BLOCKS = 500;
const MAX_LABEL = 200;
const MAX_ID_LEN = 64;
const MAX_CONTENT = 5000;
const COORD_LIMIT = 10000;

/** Допустимые выравнивания содержимого блока. */
const ALIGNS: Align[] = ['left', 'center', 'right'];

/**
 * Стартовое дерево нового проекта.
 * Должно совпадать с default_tree() на сервере (projects/models.py):
 * это два конца одного контракта.
 *
 * Поля kind здесь нет намеренно: вид заливки — производная величина от
 * module (см. kindOf в moduleRegistry). Хранить его в данных означало бы
 * держать в базе значение, которое может разойтись с реестром модулей.
 */
export function defaultTree(): PageTree {
  const blocks: Block[] = [
    { id: 'b1', module: 'section.hero', x: 40, y: 40, width: 640, height: 200, label: 'Первый экран' },
    { id: 'b2', module: 'text.heading', x: 40, y: 264, width: 640, height: 64, label: 'Заголовок' },
    { id: 'b3', module: 'media.image', x: 40, y: 352, width: 300, height: 180, label: 'Изображение' },
    { id: 'b4', module: 'text.paragraph', x: 364, y: 352, width: 316, height: 180, label: 'Описание' },
  ];
  return { width: 720, blocks };
}

/**
 * Проверка дерева на клиенте.
 *
 * Дублирует серверную проверку намеренно: она даёт мгновенную обратную
 * связь, пока пользователь двигает блок, и не отправляет заведомо
 * битые данные. Серверная проверка остаётся обязательной — клиентскую
 * можно обойти.
 *
 * Возвращает текст первой ошибки либо null.
 */
export function validateTree(value: unknown): string | null {
  if (typeof value !== 'object' || value === null) return 'tree: ожидается объект';
  const t = value as Record<string, unknown>;

  const width = t.width;
  if (typeof width !== 'number' || !Number.isFinite(width) || width <= 0) {
    return 'tree.width: ожидается положительное число';
  }
  if (width > COORD_LIMIT) return 'tree.width: слишком велико';

  if (!Array.isArray(t.blocks)) return 'tree.blocks: ожидается массив';
  if (t.blocks.length > MAX_BLOCKS) return `tree.blocks: больше ${MAX_BLOCKS} блоков`;

  const ids = new Set<string>();
  for (const [i, raw] of t.blocks.entries()) {
    const p = `tree.blocks[${i}]: `;
    if (typeof raw !== 'object' || raw === null) return p + 'ожидается объект';
    const b = raw as Record<string, unknown>;

    const blockId = b.id;
    if (typeof blockId !== 'string' || blockId.length === 0 || blockId.length > MAX_ID_LEN) {
      return p + `id должен быть строкой 1–${MAX_ID_LEN} символа`;
    }
    if (ids.has(blockId)) return p + `повторяющийся id "${blockId}"`;
    ids.add(blockId);

    for (const k of ['x', 'y', 'width', 'height'] as const) {
      const v = b[k];
      if (typeof v !== 'number' || !Number.isFinite(v)) return p + `${k}: ожидается число`;
      if (v < -COORD_LIMIT || v > COORD_LIMIT) return p + `${k}: вне диапазона`;
    }
    if ((b.width as number) <= 0 || (b.height as number) <= 0) {
      return p + 'width и height должны быть положительными';
    }

    const moduleId = b.module;
    if (typeof moduleId !== 'string' || !MODULE_IDS.has(moduleId)) {
      return p + `module: неизвестный модуль "${String(moduleId)}"`;
    }

    if (typeof b.label !== 'string' || b.label.length > MAX_LABEL) {
      return p + `label: строка до ${MAX_LABEL} символов`;
    }

    if (b.align !== undefined && !ALIGNS.includes(b.align as Align)) {
      return p + `align: допустимо ${ALIGNS.join(', ')}`;
    }
    if (b.align !== undefined && typeof b.align !== 'string') {
      return p + 'align: строка';
    }

    if (b.content !== undefined) {
      if (typeof b.content !== 'string') return p + 'content: строка';
      if (b.content.length > MAX_CONTENT) {
        return p + `content: длиннее ${MAX_CONTENT} символов`;
      }
    }
  }
  return null;
}

/** Новый идентификатор экземпляра блока. */
let blockCounter = 0;
export function newBlockId(): string {
  blockCounter += 1;
  return `b${Date.now().toString(36)}-${blockCounter}`;
}
