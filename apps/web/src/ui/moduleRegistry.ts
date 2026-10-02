/*
 * СГЕНЕРИРОВАНО — не править руками. Источник: packages/registry/modules.json
 * Генератор: packages/registry/build.mjs
 * Исходный документ: docs/MODULE-CATALOG.md
 *
 * Реестр приходит из Control Plane при старте редактора; этот файл
 * нужен для офлайн-подсказок и для типов, чтобы палитра модулей
 * работала и без сети.
 */

export type ModuleKind = 'section' | 'text' | 'media';

export interface ModuleDef {
  id: string;
  name: string;
  category: string;
  categoryLabel: string;
  kind: ModuleKind;
  stages: number[];
  minStage: number;
}

export interface CategoryDef {
  code: string;
  id: string;
  label: string;
}

export const MODULE_CATEGORIES: CategoryDef[] = [
  { code: 'A', id: 'structure', label: 'Структурные секции' },
  { code: 'B', id: 'content', label: 'Контентные модули' },
  { code: 'C', id: 'data', label: 'Модули данных' },
  { code: 'D', id: 'commerce', label: 'Коммерческие модули' },
  { code: 'E', id: 'trust', label: 'Секции доверия и соответствия' },
];

export const MODULES: ModuleDef[] = [
  { id: 'section.split', name: 'Две колонки', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'section.cards', name: 'Карточки', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'section.spacer', name: 'Отступ', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'section.hero', name: 'Первый экран', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'section.footer', name: 'Подвал', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'section.feature', name: 'Преимущества', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'section.cta', name: 'Призыв к действию', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'section.header', name: 'Шапка', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [3], minStage: 3 },
  { id: 'media.video', name: 'Видео', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'media.embed', name: 'Встраивание', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'text.heading', name: 'Заголовок', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'media.image', name: 'Изображение', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'action.button', name: 'Кнопка', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'seo.schema', name: 'Микроразметка', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'text.list', name: 'Список', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'action.link', name: 'Ссылка', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'text.paragraph', name: 'Текст', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'action.form', name: 'Форма', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'nav.breadcrumb', name: 'Хлебные крошки', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'text.quote', name: 'Цитата', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [3], minStage: 3 },
  { id: 'data.collection', name: 'Коллекция записей', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [3], minStage: 3 },
  { id: 'data.single', name: 'Одна запись', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [3], minStage: 3 },
  { id: 'data.search', name: 'Поиск', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [3], minStage: 3 },
  { id: 'data.field', name: 'Поле', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [3], minStage: 3 },
  { id: 'data.pagination', name: 'Постраничная навигация', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [3], minStage: 3 },
  { id: 'data.list', name: 'Список', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [3], minStage: 3 },
  { id: 'section.accordion', name: 'Аккордеон', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [5], minStage: 5 },
  { id: 'section.tabs', name: 'Вкладки', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [5], minStage: 5 },
  { id: 'section.gallery', name: 'Галерея', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [5], minStage: 5 },
  { id: 'section.timeline', name: 'Таймлайн', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [5], minStage: 5 },
  { id: 'section.steps', name: 'Шаги', category: 'structure', categoryLabel: 'Структурные секции', kind: 'section', stages: [5], minStage: 5 },
  { id: 'media.audio', name: 'Аудио', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [5], minStage: 5 },
  { id: 'text.code', name: 'Код', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [5], minStage: 5 },
  { id: 'code.custom', name: 'Произвольный код', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [5], minStage: 5 },
  { id: 'social.links', name: 'Соцсети', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [5], minStage: 5 },
  { id: 'text.table', name: 'Таблица', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [5], minStage: 5 },
  { id: 'media.file', name: 'Файл', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [5], minStage: 5 },
  { id: 'nav.anchor', name: 'Якорь', category: 'content', categoryLabel: 'Контентные модули', kind: 'text', stages: [5], minStage: 5 },
  { id: 'data.aggregate', name: 'Агрегат', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [5], minStage: 5 },
  { id: 'data.related', name: 'Связанные записи', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [5], minStage: 5 },
  { id: 'data.sort', name: 'Сортировка', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [5], minStage: 5 },
  { id: 'data.count', name: 'Счётчик', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [5], minStage: 5 },
  { id: 'data.filter', name: 'Фильтр', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [5], minStage: 5 },
  { id: 'data.form', name: 'Форма записи', category: 'data', categoryLabel: 'Модули данных', kind: 'text', stages: [5], minStage: 5 },
  { id: 'legal.age-mark', name: 'Возрастная маркировка', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'trust.logos', name: 'Логотипы клиентов', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'legal.ad-mark', name: 'Маркировка рекламы', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'trust.review', name: 'Отзывы клиентов', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'legal.offer', name: 'Оферта', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'legal.policy', name: 'Политика конфиденциальности', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'trust.rating', name: 'Рейтинг', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'legal.requisites', name: 'Реквизиты', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'legal.consent', name: 'Согласие на обработку ПДн', category: 'trust', categoryLabel: 'Секции доверия и соответствия', kind: 'text', stages: [5], minStage: 5 },
  { id: 'shop.order', name: 'Заказ', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.card', name: 'Карточка товара', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.catalog', name: 'Каталог', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.cart', name: 'Корзина', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.stock', name: 'Остатки', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.reviews', name: 'Отзывы', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.checkout', name: 'Оформление', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.search', name: 'Поиск по каталогу', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'promo.banner', name: 'Промо-баннер', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.compare', name: 'Сравнение', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'promo.pricing', name: 'Тарифы', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
  { id: 'shop.price', name: 'Цена', category: 'commerce', categoryLabel: 'Коммерческие модули', kind: 'text', stages: [6], minStage: 6 },
];

export const MODULE_IDS: ReadonlySet<string> = new Set(
  MODULES.map((m) => m.id),
);

/** Модули, доступные на этапе выпуска. */
export function modulesForStage(stage: number): ModuleDef[] {
  return MODULES.filter((m) => m.stages.includes(stage));
}

export function moduleById(id: string): ModuleDef | undefined {
  return MODULES.find((m) => m.id === id);
}

/**
 * Вид блока на холсте. Заливка в редакторе берётся отсюда.
 * Не путать с категорией каталога: data.list — категория data,
 * но рисуется как текстовый блок.
 */
export function kindOf(moduleId: string): ModuleKind {
  return moduleById(moduleId)?.kind ?? 'text';
}
