/**
 * Модель дерева страницы — общий контракт между редактором и Control Plane.
 *
 * Формат совпадает с деревом блоков из docs/MODULE-CATALOG.md и должен
 * оставаться стабильным: он уходит в API и в экспорт (ТЗ п.16.2).
 * Поэтому типы описаны явно, а не через any.
 */

export type BlockKind = 'section' | 'text' | 'media';

export interface Block {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  kind: BlockKind;
  label: string;
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

/**
 * Дерево по умолчанию для нового проекта.
 * Временные данные до подключения Control Plane.
 */
export function defaultTree(): PageTree {
  return {
    width: 720,
    blocks: [
      { id: 'b1', x: 40, y: 40, width: 640, height: 200, kind: 'section', label: 'Первый экран' },
      { id: 'b2', x: 40, y: 264, width: 640, height: 64, kind: 'text', label: 'Заголовок' },
      { id: 'b3', x: 40, y: 352, width: 300, height: 180, kind: 'media', label: 'Изображение' },
      { id: 'b4', x: 364, y: 352, width: 316, height: 180, kind: 'text', label: 'Описание' },
    ],
  };
}

const KINDS: BlockKind[] = ['section', 'text', 'media'];

/**
 * Проверка присланного с клиента дерева.
 *
 * Сервер не может доверять данным из браузера: без проверки в PostgreSQL
 * попадёт что угодно, вплоть до поля, которое ломает экспорт.
 * Возвращает текст первой ошибки либо null.
 */
export function validateTree(value: unknown): string | null {
  if (typeof value !== 'object' || value === null) return 'tree: ожидается объект';
  const t = value as Record<string, unknown>;

  if (typeof t.width !== 'number' || !Number.isFinite(t.width) || t.width <= 0) {
    return 'tree.width: ожидается положительное число';
  }
  if (t.width > 10000) return 'tree.width: слишком велико';

  if (!Array.isArray(t.blocks)) return 'tree.blocks: ожидается массив';
  if (t.blocks.length > 500) return 'tree.blocks: больше 500 блоков';

  const ids = new Set<string>();
  for (const [i, raw] of t.blocks.entries()) {
    const p = `tree.blocks[${i}]: `;
    if (typeof raw !== 'object' || raw === null) return p + 'ожидается объект';
    const b = raw as Record<string, unknown>;

    if (typeof b.id !== 'string' || b.id.length === 0 || b.id.length > 64) {
      return p + 'id должен быть строкой 1–64 символа';
    }
    if (ids.has(b.id)) return p + `повторяющийся id "${b.id}"`;
    ids.add(b.id);

    for (const k of ['x', 'y', 'width', 'height'] as const) {
      const v = b[k];
      if (typeof v !== 'number' || !Number.isFinite(v)) return p + `${k}: ожидается число`;
      if (v < -10000 || v > 10000) return p + `${k}: вне диапазона`;
    }
    if ((b.width as number) <= 0 || (b.height as number) <= 0) {
      return p + 'width и height должны быть положительными';
    }
    if (typeof b.kind !== 'string' || !KINDS.includes(b.kind as BlockKind)) {
      return p + `kind: допустимо ${KINDS.join(', ')}`;
    }
    if (typeof b.label !== 'string' || b.label.length > 200) {
      return p + 'label: строка до 200 символов';
    }
  }
  return null;
}
