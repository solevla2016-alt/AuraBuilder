/**
 * Типограф для редактора.
 *
 * Тот же набор правил, что в `apps/projects/typography.py`: кнопка в
 * панели свойств должна показывать ровно то, что окажется в пакете
 * после экспорта. Расхождение здесь заметно не сразу — только на
 * готовом сайте, когда рядом стоят два разных тире.
 *
 * Правила консервативные: кавычки меняются только при чётном числе,
 * дефисы — только окружённые пробелами. Всё спорное остаётся как есть:
 * испорченный смысл хуже некрасивой кавычки.
 */

/** Предел, после которого строка считается выгрузкой данных. */
const MAX_TEXT = 20_000;

/**
 * Короткие слова, которые не должны оставаться в конце строки.
 * Список совпадает с SHORT_WORDS в typography.py.
 */
const SHORT_WORDS = [
  'а', 'бы', 'в', 'во', 'до', 'же', 'за', 'и', 'из', 'к', 'ко', 'ли',
  'на', 'не', 'ни', 'но', 'о', 'об', 'от', 'по', 'с', 'со', 'то', 'у', 'я',
];

const SHORT_WORD_RE = new RegExp(
  `(?<!\\p{L})(?:${[...SHORT_WORDS].sort((a, b) => b.length - a.length).join('|')})[ \\t]+`,
  'giu',
);

/** Приводит прямые кавычки к «ёлочкам», если их чётное число. */
function smartQuotes(text: string): string {
  if ((text.match(/"/g)?.length ?? 0) % 2 !== 0) return text;
  let opening = true;
  return text.replace(/"/g, () => {
    const next = opening ? '«' : '»';
    opening = !opening;
    return next;
  });
}

/** Расставляет типографские знаки. Безопасна для повторного вызова. */
export function typograph(text: string): string {
  if (!text || text.length > MAX_TEXT) return text;

  let result = text;
  // Порядок важен: сначала лишние пробелы, затем знаки, в конце —
  // неразрывные пробелы. Иначе правило коротких слов съело бы пробел
  // перед запятой.
  result = result.replace(/[ \t]{2,}/g, ' ');
  result = result.replace(/[ \t]+([,.;:!?])/g, '$1');
  result = result.replace(/\.\.\./g, '…');
  result = smartQuotes(result);
  result = result.replace(/-{2,}/g, '—');
  result = result.replace(/[ \t]+-[ \t]+/g, ' — ');
  result = result.replace(/[ \t]+—[ \t]*/g, '\u00a0— ');
  result = result.replace(SHORT_WORD_RE, '$&\u00a0');
  result = result.replace(
    /(\d)[ \t]+(?=[A-Za-zА-Яа-яЁё%₽$€])/g,
    '$1\u00a0',
  );
  return result;
}
