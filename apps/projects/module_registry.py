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
    Module('code.custom', 'Произвольный код', 'content', 'Контентные модули', 'text', (3,)),
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


@dataclass(frozen=True)
class Prop:
    """Одно настраиваемое свойство модуля."""

    name: str
    type: str
    required: bool
    default: object | None
    limits: dict
    description: str


@dataclass(frozen=True)
class ModuleSchema:
    """Схема свойств модуля."""

    module_id: str
    props: tuple[Prop, ...]

    def defaults(self) -> dict:
        """Значения по умолчанию для только что вставленного блока."""
        return {p.name: p.default for p in self.props if p.default is not None}

SCHEMAS: dict[str, ModuleSchema] = {
    'section.hero': ModuleSchema(
        'section.hero',
        (
        Prop('heading', 'text', True, "Создавайте сайты без кода", {}, 'Главный заголовок первого экрана'),
        Prop('subheading', 'textarea', False, None, {}, 'Подзаголовок под заголовком'),
        Prop('buttonLabel', 'text', False, "Опубликовать", {}, 'Надпись на кнопке действия'),
        Prop('buttonLink', 'text', False, "#", {}, 'Адрес кнопки'),
        Prop('background', 'select', True, "light", {"options":["light","accent","dark"]}, 'Заливка секции'),
        Prop('align', 'select', True, "left", {"options":["left","center","right"]}, 'Выравнивание текста'),
        Prop('size', 'select', True, "regular", {"options":["compact","regular","fullscreen"]}, 'Высота первого экрана'),
        ),
    ),
    'text.heading': ModuleSchema(
        'text.heading',
        (
        Prop('text', 'text', True, "Заголовок", {}, 'Текст заголовка'),
        Prop('level', 'select', True, "h2", {"options":["h2","h3","h4"]}, 'Уровень заголовка'),
        Prop('align', 'select', True, "left", {"options":["left","center","right"]}, 'Выравнивание'),
        ),
    ),
    'text.paragraph': ModuleSchema(
        'text.paragraph',
        (
        Prop('text', 'textarea', True, "Расскажите о вашем проекте", {}, 'Текст абзаца'),
        Prop('align', 'select', True, "left", {"options":["left","center","right"]}, 'Выравнивание'),
        Prop('maxWidth', 'number', False, 720, {"min":240,"max":960,"step":40}, 'Ограничение ширины строки, px'),
        ),
    ),
    'section.split': ModuleSchema(
        'section.split',
        (
        Prop('heading', 'text', False, "Левая колонка", {}, 'Заголовок левой колонки'),
        ),
    ),
    'section.cards': ModuleSchema(
        'section.cards',
        (
        Prop('heading', 'text', False, "Подборка", {}, 'Заголовок секции карточек'),
        Prop('columns', 'number', False, 3, {"min":2,"max":4,"step":1}, 'Сколько карточек показывать'),
        ),
    ),
    'section.cta': ModuleSchema(
        'section.cta',
        (
        Prop('heading', 'text', False, "Остались вопросы?", {}, 'Заголовок призыва к действию'),
        Prop('buttonLabel', 'text', False, "Связаться", {}, 'Подпись кнопки'),
        ),
    ),
    'section.accordion': ModuleSchema(
        'section.accordion',
        (
        Prop('heading', 'text', False, "Частые вопросы", {}, 'Заголовок секции'),
        Prop('items', 'textarea', True, "Как оформить заказ?;Где доставка?;Как вернуть?", {}, 'Вопросы по одному в строке'),
        Prop('firstOpen', 'boolean', False, True, {}, 'Раскрыть первый пункт при загрузке'),
        Prop('allowMultiple', 'boolean', False, False, {}, 'Разрешить несколько раскрытых пунктов'),
        ),
    ),
    'section.tabs': ModuleSchema(
        'section.tabs',
        (
        Prop('heading', 'text', False, "Как это работает", {}, 'Заголовок секции'),
        Prop('tabs', 'textarea', True, "Подготовка;Проверка;Доставка", {}, 'Подписи вкладок по одной в строке'),
        Prop('columns', 'number', False, 3, {"min":2,"max":4,"step":1}, 'Сколько вкладок показывать'),
        ),
    ),
    'section.gallery': ModuleSchema(
        'section.gallery',
        (
        Prop('heading', 'text', False, "Работы", {}, 'Заголовок галереи'),
        Prop('columns', 'number', False, 3, {"min":2,"max":5,"step":1}, 'Сколько изображений в ряд'),
        Prop('gap', 'number', False, 16, {"min":4,"max":48,"step":4}, 'Промежуток между кадрами, px'),
        ),
    ),
    'section.timeline': ModuleSchema(
        'section.timeline',
        (
        Prop('heading', 'text', False, "История", {}, 'Заголовок секции'),
        Prop('year', 'text', True, "2019", {}, 'Год у первого события'),
        Prop('stepYears', 'number', False, 2, {"min":1,"max":10,"step":1}, 'Разница между годами'),
        Prop('events', 'number', False, 4, {"min":2,"max":8,"step":1}, 'Сколько событий показать'),
        ),
    ),
    'section.steps': ModuleSchema(
        'section.steps',
        (
        Prop('heading', 'text', False, "Три шага", {}, 'Заголовок секции'),
        Prop('steps', 'textarea', True, "Заявка;Согласование;Работа", {}, 'Названия шагов по одному в строке'),
        Prop('showNumbers', 'boolean', False, True, {}, 'Показывать номера шагов'),
        ),
    ),
    'legal.offer': ModuleSchema(
        'legal.offer',
        (
        Prop('heading', 'text', True, "Публичная оферта", {}, 'Заголовок документа'),
        Prop('body', 'textarea', True, "Текст оферты размещается здесь.", {}, 'Полный текст документа'),
        Prop('updated', 'text', False, None, {}, 'Дата редакции документа'),
        ),
    ),
    'legal.policy': ModuleSchema(
        'legal.policy',
        (
        Prop('heading', 'text', True, "Политика конфиденциальности", {}, 'Заголовок документа'),
        Prop('body', 'textarea', True, "Текст политики размещается здесь.", {}, 'Полный текст документа'),
        Prop('updated', 'text', False, None, {}, 'Дата редакции документа'),
        ),
    ),
    'legal.requisites': ModuleSchema(
        'legal.requisites',
        (
        Prop('heading', 'text', False, "Реквизиты", {}, 'Заголовок блока'),
        Prop('name', 'text', True, "Наименование организации", {}, 'Полное наименование с организационно-правовой формой'),
        Prop('inn', 'text', True, "0000000000", {}, 'ИНН'),
        Prop('ogrn', 'text', False, None, {}, 'ОГРН или ОГРНИП'),
        Prop('address', 'text', True, "Адрес", {}, 'Юридический адрес'),
        Prop('email', 'text', False, None, {}, 'Почта для обращений'),
        ),
    ),
    'legal.consent': ModuleSchema(
        'legal.consent',
        (
        Prop('text', 'text', True, "Я согласен на обработку персональных данных", {}, 'Текст согласия рядом с флажком'),
        Prop('link', 'text', True, "/privacy-policy", {}, 'Адрес политики конфиденциальности'),
        Prop('required', 'boolean', False, True, {}, 'Обязательный флажок'),
        ),
    ),
    'legal.age-mark': ModuleSchema(
        'legal.age-mark',
        (
        Prop('text', 'text', True, "18+", {}, 'Надпись маркировки'),
        Prop('note', 'text', False, None, {}, 'Пояснение под маркировкой'),
        ),
    ),
    'legal.ad-mark': ModuleSchema(
        'legal.ad-mark',
        (
        Prop('text', 'text', True, "Реклама", {}, 'Надпись маркировки рекламы'),
        Prop('href', 'text', False, None, {}, 'Адрес сведений о рекламе'),
        Prop('label', 'text', False, None, {}, 'Надпись ссылки'),
        ),
    ),
    'trust.logos': ModuleSchema(
        'trust.logos',
        (
        Prop('heading', 'text', False, "Нам доверяют", {}, 'Заголовок блока'),
        Prop('items', 'textarea', True, "Клиент;Клиент;Клиент", {}, 'Названия компаний по одному в строке'),
        Prop('grayscale', 'boolean', False, True, {}, 'Приглушать логотипы'),
        ),
    ),
    'trust.review': ModuleSchema(
        'trust.review',
        (
        Prop('author', 'text', True, "Покупатель", {}, 'Имя автора отзыва'),
        Prop('rating', 'number', True, 5, {"min":1,"max":5,"step":1}, 'Оценка'),
        Prop('text', 'textarea', True, "Отзыв покупателя о работе магазина.", {}, 'Текст отзыва'),
        ),
    ),
    'trust.rating': ModuleSchema(
        'trust.rating',
        (
        Prop('value', 'number', True, 4.8, {"min":0,"max":5,"step":0.1}, 'Средняя оценка'),
        Prop('count', 'number', True, 120, {"min":0,"max":100000,"step":1}, 'Сколько отзывов учтено'),
        Prop('source', 'text', False, None, {}, 'Источник оценок'),
        ),
    ),
    'data.count': ModuleSchema(
        'data.count',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('label', 'text', False, "Всего", {}, 'Подпись над числом'),
        Prop('field', 'text', False, None, {}, 'Ключ поля; пусто — считаются все записи'),
        ),
    ),
    'data.aggregate': ModuleSchema(
        'data.aggregate',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('field', 'text', True, "title", {}, 'Ключ поля, по которому считается итог'),
        Prop('op', 'select', True, "sum", {"options":["sum","avg","min","max","count"]}, 'Что именно считается'),
        Prop('label', 'text', False, "Итого", {}, 'Подпись к значению'),
        Prop('suffix', 'text', False, None, {}, 'Единица измерения после значения'),
        ),
    ),
    'data.filter': ModuleSchema(
        'data.filter',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('field', 'text', True, "title", {}, 'Ключ поля, по которому отбираются записи'),
        Prop('operator', 'select', True, "eq", {"options":["eq","contains","gt","lt"]}, 'Условие отбора'),
        Prop('value', 'text', False, None, {}, 'Значение для сравнения; пусто — отбираются непустые'),
        Prop('label', 'text', False, None, {}, 'Надпись над результатом'),
        ),
    ),
    'data.sort': ModuleSchema(
        'data.sort',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('field', 'text', True, "title", {}, 'Ключ поля для сортировки'),
        Prop('direction', 'select', True, "asc", {"options":["asc","desc"]}, 'Направление сортировки'),
        Prop('limit', 'number', False, 10, {"min":1,"max":100,"step":1}, 'Сколько записей показать'),
        ),
    ),
    'data.related': ModuleSchema(
        'data.related',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('field', 'text', False, None, {}, 'Ключ поля, по которому ищутся связанные записи'),
        Prop('titleField', 'text', False, None, {}, 'Ключ поля для заголовка карточки'),
        Prop('limit', 'number', False, 4, {"min":1,"max":24,"step":1}, 'Сколько связанных записей показать'),
        ),
    ),
    'data.form': ModuleSchema(
        'data.form',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('heading', 'text', False, "Форма", {}, 'Заголовок формы'),
        Prop('fields', 'textarea', True, "Имя;Телефон", {}, 'Поля формы по одному в строке'),
        Prop('submitLabel', 'text', False, "Отправить", {}, 'Надпись на кнопке'),
        Prop('note', 'text', False, None, {}, 'Пояснение под формой'),
        ),
    ),
    'media.audio': ModuleSchema(
        'media.audio',
        (
        Prop('title', 'text', True, "Аудио", {}, 'Название записи'),
        Prop('src', 'text', False, None, {}, 'Адрес файла; пусто — файл не подключён'),
        Prop('autoplay', 'boolean', False, False, {}, 'Проигрывать автоматически'),
        Prop('loop', 'boolean', False, False, {}, 'Повторять'),
        ),
    ),
    'text.code': ModuleSchema(
        'text.code',
        (
        Prop('heading', 'text', False, None, {}, 'Заголовок над блоком'),
        Prop('code', 'textarea', True, "console.log('Привет, мир!');", {}, 'Текст кода'),
        Prop('language', 'select', True, "js", {"options":["js","json","html","css","bash","text"]}, 'Язык для подсветки'),
        ),
    ),
    'social.links': ModuleSchema(
        'social.links',
        (
        Prop('heading', 'text', False, "Мы здесь", {}, 'Заголовок над списком'),
        Prop('links', 'textarea', True, "https://example.com/social", {}, 'Адреса по одному в строке'),
        ),
    ),
    'text.table': ModuleSchema(
        'text.table',
        (
        Prop('heading', 'text', False, None, {}, 'Заголовок над таблицей'),
        Prop('rows', 'textarea', True, "Услуга;Стоимость;Срок\\nАудит;30 000 ₽;3 дня", {}, 'Строки таблицы; первая — заголовки, разделитель столбцов точка с запятой'),
        ),
    ),
    'media.file': ModuleSchema(
        'media.file',
        (
        Prop('title', 'text', True, "Файл", {}, 'Название файла для посетителя'),
        Prop('href', 'text', False, None, {}, 'Адрес файла; пусто — ссылка ведёт в никуда'),
        Prop('size', 'text', False, None, {}, 'Размер файла подписью, например 2,4 МБ'),
        ),
    ),
    'nav.anchor': ModuleSchema(
        'nav.anchor',
        (
        Prop('anchor', 'text', True, "section", {}, 'Имя метки; на него ссылается меню'),
        Prop('label', 'text', False, None, {}, 'Подпись для навигации поиском по странице'),
        ),
    ),
    'action.button': ModuleSchema(
        'action.button',
        (
        Prop('label', 'text', True, "Кнопка", {}, 'Текст на кнопке'),
        Prop('link', 'text', False, "#", {}, 'Адрес перехода'),
        ),
    ),
    'action.link': ModuleSchema(
        'action.link',
        (
        Prop('label', 'text', True, "Ссылка", {}, 'Текст ссылки'),
        Prop('link', 'text', False, "#", {}, 'Адрес перехода'),
        ),
    ),
    'data.collection': ModuleSchema(
        'data.collection',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('limit', 'number', False, 6, {"min":1,"max":24,"step":1}, 'Сколько записей показывать'),
        ),
    ),
    'data.single': ModuleSchema(
        'data.single',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        ),
    ),
    'data.field': ModuleSchema(
        'data.field',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('field', 'text', True, "title", {}, 'Ключ поля записи'),
        Prop('label', 'text', False, "Поле", {}, 'Подпись слева от значения'),
        ),
    ),
    'data.list': ModuleSchema(
        'data.list',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('limit', 'number', False, 10, {"min":1,"max":50,"step":1}, 'Сколько строк показывать'),
        ),
    ),
    'data.search': ModuleSchema(
        'data.search',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('placeholder', 'text', False, "Поиск по узлу данных", {}, 'Подсказка в поле'),
        ),
    ),
    'data.pagination': ModuleSchema(
        'data.pagination',
        (
        Prop('source', 'text', False, None, {}, 'Идентификатор источника данных; пусто — источник не выбран'),
        Prop('limit', 'number', False, 10, {"min":1,"max":50,"step":1}, 'Записей на страницу'),
        ),
    ),
}

SCHEMA_IDS: frozenset[str] = frozenset(SCHEMAS)


def schema_for(module_id: str) -> ModuleSchema | None:
    """Схема свойств модуля либо None, если модуль её не описал."""
    return SCHEMAS.get(module_id)


def modules_for_stage(stage: int) -> tuple[Module, ...]:
    """Модули, доступные на указанном этапе выпуска."""
    return tuple(m for m in MODULES if stage in m.stages)
