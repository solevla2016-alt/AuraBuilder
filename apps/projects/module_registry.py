"""Реестр модулей редактора для Control Plane.

* СГЕНЕРИРОВАНО — не править руками. Источник: packages/registry/modules.json
 * Генератор: packages/registry/build.mjs
 * Исходный документ: docs/MODULE-CATALOG.md

Используется в двух местах: валидация дерева страницы и эндпоинт
каталога модулей. Список намеренно заморожен в момент импорта —
модули добавляются выпуском, а не правкой этого файла.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    """Описание модуля редактора."""

    id: str
    name: str
    category: str
    category_label: str
    kind: str
    stages: tuple[int, ...]

    @property
    def min_stage(self) -> int:
        """Ранний этап, на котором модуль доступен."""
        return min(self.stages)


CATEGORIES: tuple[dict[str, str], ...] = (
    {'code': 'A', 'id': 'structure', 'label': 'Структурные секции'},
    {'code': 'B', 'id': 'content', 'label': 'Контентные модули'},
    {'code': 'C', 'id': 'data', 'label': 'Модули данных'},
    {'code': 'D', 'id': 'commerce', 'label': 'Коммерческие модули'},
    {'code': 'E', 'id': 'trust', 'label': 'Секции доверия и соответствия'},
)

MODULES: tuple[Module, ...] = (
    Module('section.split', 'Две колонки', 'structure', 'Структурные секции', 'section', (3,)),
    Module('section.cards', 'Карточки', 'structure', 'Структурные секции', 'section', (3,)),
    Module('section.spacer', 'Отступ', 'structure', 'Структурные секции', 'section', (3,)),
    Module('section.hero', 'Первый экран', 'structure', 'Структурные секции', 'section', (3,)),
    Module('section.footer', 'Подвал', 'structure', 'Структурные секции', 'section', (3,)),
    Module('section.feature', 'Преимущества', 'structure', 'Структурные секции', 'section', (3,)),
    Module('section.cta', 'Призыв к действию', 'structure', 'Структурные секции', 'section', (3,)),
    Module('section.header', 'Шапка', 'structure', 'Структурные секции', 'section', (3,)),
    Module('media.video', 'Видео', 'content', 'Контентные модули', 'text', (3,)),
    Module('media.embed', 'Встраивание', 'content', 'Контентные модули', 'text', (3,)),
    Module('text.heading', 'Заголовок', 'content', 'Контентные модули', 'text', (3,)),
    Module('media.image', 'Изображение', 'content', 'Контентные модули', 'text', (3,)),
    Module('action.button', 'Кнопка', 'content', 'Контентные модули', 'text', (3,)),
    Module('seo.schema', 'Микроразметка', 'content', 'Контентные модули', 'text', (3,)),
    Module('text.list', 'Список', 'content', 'Контентные модули', 'text', (3,)),
    Module('action.link', 'Ссылка', 'content', 'Контентные модули', 'text', (3,)),
    Module('text.paragraph', 'Текст', 'content', 'Контентные модули', 'text', (3,)),
    Module('action.form', 'Форма', 'content', 'Контентные модули', 'text', (3,)),
    Module('nav.breadcrumb', 'Хлебные крошки', 'content', 'Контентные модули', 'text', (3,)),
    Module('text.quote', 'Цитата', 'content', 'Контентные модули', 'text', (3,)),
    Module('data.collection', 'Коллекция записей', 'data', 'Модули данных', 'text', (3,)),
    Module('data.single', 'Одна запись', 'data', 'Модули данных', 'text', (3,)),
    Module('data.search', 'Поиск', 'data', 'Модули данных', 'text', (3,)),
    Module('data.field', 'Поле', 'data', 'Модули данных', 'text', (3,)),
    Module('data.pagination', 'Постраничная навигация', 'data', 'Модули данных', 'text', (3,)),
    Module('data.list', 'Список', 'data', 'Модули данных', 'text', (3,)),
    Module('section.accordion', 'Аккордеон', 'structure', 'Структурные секции', 'section', (5,)),
    Module('section.tabs', 'Вкладки', 'structure', 'Структурные секции', 'section', (5,)),
    Module('section.gallery', 'Галерея', 'structure', 'Структурные секции', 'section', (5,)),
    Module('section.timeline', 'Таймлайн', 'structure', 'Структурные секции', 'section', (5,)),
    Module('section.steps', 'Шаги', 'structure', 'Структурные секции', 'section', (5,)),
    Module('media.audio', 'Аудио', 'content', 'Контентные модули', 'text', (5,)),
    Module('text.code', 'Код', 'content', 'Контентные модули', 'text', (5,)),
    Module('code.custom', 'Произвольный код', 'content', 'Контентные модули', 'text', (5,)),
    Module('social.links', 'Соцсети', 'content', 'Контентные модули', 'text', (5,)),
    Module('text.table', 'Таблица', 'content', 'Контентные модули', 'text', (5,)),
    Module('media.file', 'Файл', 'content', 'Контентные модули', 'text', (5,)),
    Module('nav.anchor', 'Якорь', 'content', 'Контентные модули', 'text', (5,)),
    Module('data.aggregate', 'Агрегат', 'data', 'Модули данных', 'text', (5,)),
    Module('data.related', 'Связанные записи', 'data', 'Модули данных', 'text', (5,)),
    Module('data.sort', 'Сортировка', 'data', 'Модули данных', 'text', (5,)),
    Module('data.count', 'Счётчик', 'data', 'Модули данных', 'text', (5,)),
    Module('data.filter', 'Фильтр', 'data', 'Модули данных', 'text', (5,)),
    Module('data.form', 'Форма записи', 'data', 'Модули данных', 'text', (5,)),
    Module('legal.age-mark', 'Возрастная маркировка', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('trust.logos', 'Логотипы клиентов', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('legal.ad-mark', 'Маркировка рекламы', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('trust.review', 'Отзывы клиентов', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('legal.offer', 'Оферта', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('legal.policy', 'Политика конфиденциальности', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('trust.rating', 'Рейтинг', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('legal.requisites', 'Реквизиты', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('legal.consent', 'Согласие на обработку ПДн', 'trust', 'Секции доверия и соответствия', 'text', (5,)),
    Module('shop.order', 'Заказ', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.card', 'Карточка товара', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.catalog', 'Каталог', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.cart', 'Корзина', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.stock', 'Остатки', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.reviews', 'Отзывы', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.checkout', 'Оформление', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.search', 'Поиск по каталогу', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('promo.banner', 'Промо-баннер', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.compare', 'Сравнение', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('promo.pricing', 'Тарифы', 'commerce', 'Коммерческие модули', 'text', (6,)),
    Module('shop.price', 'Цена', 'commerce', 'Коммерческие модули', 'text', (6,)),
)

MODULES_BY_ID: dict[str, Module] = {m.id: m for m in MODULES}
MODULE_IDS: frozenset[str] = frozenset(MODULES_BY_ID)

#: Виды блока на холсте: от них зависит заливка в редакторе.
KINDS: frozenset[str] = frozenset({m.kind for m in MODULES})


def modules_for_stage(stage: int) -> tuple[Module, ...]:
    """Модули, доступные на указанном этапе выпуска."""
    return tuple(m for m in MODULES if stage in m.stages)
