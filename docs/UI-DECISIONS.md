# UI-решения по конструктору AuraBuilder

Дата: 1 октября 2026
Источник: 13 HTML-файлов с вариантами экранов (`Qwen_html_20261001_*.html`)
Смежный документ: `docs/design-tokens.ts` — единственный источник цветов, шрифтов, отступов, радиусов, теней и таймингов.

## 1. Как читать это решение

Шаблоны — это **визуальный reference**, а не код для переноса. Аудит
(`tools/audit_templates.py`) показал общие для всех 13 файлов дефекты:

| Проблема | Охват | Решение |
|----------|-------|---------|
| Google Fonts через CDN | 13/13 | Self-hosted WOFF2 в `apps/web/public/fonts`, `font-display: swap` |
| Нет `prefers-reduced-motion` | 13/13 | Обязательный `@media (prefers-reduced-motion: reduce)` в дизайн-системе |
| Нет ARIA-ролей и `aria-*` | 13/13 | Роли задаются в компонентах, не в разметке страниц |
| Иконки — emoji в тексте | 13/13 | Собственный набор SVG (24×24, currentColor), без emoji в интерфейсе |
| `outline: none` без замены | 0–5 на экран | `:focus-visible` с 2px-ободком из токенов, всегда |
| Инлайновые стили | 2–5 на экран | Только CSS Modules + токены; inline допускается для динамических значений |
| Огромный `z-index` (до 16) | 13/13 | Шкала слоёв из токенов: `0–4` |
| Свои keyframes-анимации | 0–8 на экран | Общие анимации `fade-in`, `slide-up`, `pulse` в дизайн-системе |

## 2. Сводная таблица выбранных вариантов

| Экран | Выбран | Варианты в исходнике |
|-------|--------|---------------------|
| Editor Canvas | **V1 Floating Palette** | V1 Floating Palette, V2 Classic IDE, V3 Bottom-Heavy, V4 Minimal, V5 Split Canvas, V6 AI Command Center, V7 Zen Mode |
| Project Page | **V6 Sidebar** | V1 Classic, V2 Split, V3 Dashboard, V4 Timeline, V5 Tab-based, V6 Sidebar, V7 Focus |
| Dashboard | **V1 Сетка** | V1 Сетка, V2–V4 (не размечены), V5 Timeline, V6 Masonry, V7 Split, V8 Analytics Dashboard, V9 Focus |
| Modules Library | **V7 Inline Insert** + V2 Modal Grid | V1 Sidebar, V2 Modal Grid, V3 Floating Quick Add, V4 Categories Tabs, V5 AI-Powered, V6 Masonry Showcase, V7 Inline Insert |
| Data Nodes | **V1 Table** + V3 Split | V1 Table, V2 Card Grid, V3 Split, V4 Kanban, V5 Gallery, V6 Timeline, V7 Dashboard |
| Logic Graph | **V1 Classic Flow** + V7 Debug | V1 Classic Flow, V2 Horizontal Flow, V3 Tree, V4 Code+Graph, V5 Minimal, V6 AI Assistant, V7 Debug Mode |
| Publish Panel | **V5 Drawer** + V6 Command Center | V1 Wizard, V2 Single Page, V3 Split, V4 Modal, V5 Drawer, V6 Command Center, V7 Minimal |
| Export | **V2 Scenario Cards** + V6 Timeline | V1 Wizard, V2 Scenario Cards, V3 Split, V4 Command Center, V5 Quick Export, V6 Timeline with Progress, V7 Tab-based |
| Analytics | **V1 Classic Dashboard** + V3 E-commerce | V1 Classic Dashboard, V2 Project Analytics, V3 E-commerce, V4 SEO & Traffic, V5 Real-time, V6 Comparison, V7 KPI Minimal |
| Billing | **V2 Current Plan Focus** + V1 Classic Pricing | V1 Classic Pricing, V2 Current Plan Focus, V3 Split, V4 Dashboard, V5 Timeline, V6 Modal Upgrade, V7 Minimal |
| Notifications | **V1 Classic Inbox** + V4 Priority | V1 Classic Inbox, V2 Timeline Feed, V3 Kanban by Type, V4 Priority-based, V5 Split, V6 Command Center, V7 Minimal Focus |
| Project Settings | **V1 Classic Tabs** + V7 Accordion | V1 Classic Tabs, V2 Sidebar Nav, V3 All Sections, V4 Card Grid, V5 Split, V6 Wizard Cards, V7 Minimal Accordion |
| Support | **V1 Classic Help Center** + V2 Ticket System | V1 Classic Help Center, V2 Ticket System, V3 Chat-based, V4 Knowledge Base, V5 Split, V6 Command Center, V7 Minimal |

Где выбраны два варианта — это «основной + специализация», а не
«два варианта в одном экране».

## 3. Обоснование по ключевым экранам

### 3.1 Editor Canvas — V1 Floating Palette

Плавающая панель оставляет максимум площади под canvas, что критично для
конструктора: пользователь должен видеть страницу, а не интерфейс.

- Панель сворачивается в одну иконку, не перекрывая рабочую область.
- Инструменты группируются по контексту выделенного элемента, а не по
  расположению на экране.
- Тёмный вариант (V7 Zen Mode) берём как режим фокуса — он включается
  пользователем, а не является состоянием по умолчанию.
- V2 Classic IDE отклонён: три тяжёлых панели одновременно отнимают
  примерно половину ширины на ноутбуке 1366px.
- V5 Split Canvas оставлен для режима отладки логики, но не как основа.

### 3.2 Modules Library — V7 Inline Insert + V2 Modal Grid

Инлайновое добавление в позиции курсора — единственный вариант, который не
требует «прыгать» между канвасом и библиотекой. Поэтому:

- V7 (Inline Insert) — основной путь добавления модуля.
- V2 (Modal Grid) — полный каталог с поиском и фильтрами, когда пользователь
  не знает, что ищет.
- V5 (AI-Powered) отложен: ИИ-подбор модулей не входит в MVP.
- V6 (Masonry Showcase) отклонён: витрина красива, но плохо сканируется
  и не подходит для рабочего инструмента.

### 3.3 Data Nodes — V1 Table + V3 Split

- V1 Table (Airtable-стиль) — для массового редактирования записей,
  базовый сценарий.
- V3 Split — список коллекций слева, выбранная сущность справа: экономит
  переходы при работе со схемой.
- V4 Kanban применяется только к модулю `data.kanban`, а не к интерфейсу
  конструктора данных: это бизнес-экран будущего приложения.

### 3.4 Logic Graph — V1 Classic Flow + V7 Debug

- V1 — основа редактора логики: вертикальный поток, предсказуемый.
- V7 (Debug) включается при запуске сценария: пошаговый прогон, значения
  переменных, точки остановки.
- V4 (Code + Graph) берём позже, когда появится просмотр сгенерированного
  кода (этап 5+).

### 3.5 Publish Panel — V5 Drawer + V6 Command Center

- V5 Drawer — публикация не должна закрывать canvas: пользователь видит
  результат и список проблем одновременно.
- V6 Command Center — отдельная страница со сводкой: чек-лист, история
  публикаций, домены, SSL-статус.
- V1 Wizard отклонён: публикация повторяемая операция, а не разовый
  мастер.

### 3.6 Dashboard — V1 Сетка

Сетка карточек с фильтрами и статусами — самый предсказуемый вариант для
списка проектов, и он уже содержит фильтры, черновики, «в разработке»,
опубликованные. V9 Focus Mode пригодится для мобильной версии.

### 3.7 Остальные экраны

- **Project Page (V6 Sidebar)** — единая навигация проекта слева
  (структура, модули, логика, данные, публикация, экспорт).
- **Export (V2 Scenario Cards + V6 Timeline)** — выбор сценария карточками,
  прогресс и история таймлайном.
- **Analytics (V1 + V3)** — общий дашборд и отдельный блок e-commerce
  метрик, когда в проекте подключён commerce-модуль.
- **Billing (V2 + V1)** — текущий тариф и следующее списание наверху,
  сравнение тарифов ниже.
- **Notifications (V1 + V4)** — inbox с фильтром по приоритету; V2
  Timeline дублирует ленту событий проекта.
- **Project Settings (V1 + V7)** — табы для частых правок, accordion для
  длинных секций (SEO, домены, интеграции).
- **Support (V1 + V2)** — база знаний и тикеты; чат (V3) отложен.

## 4. Что переносим, а что выбрасываем

Переносим: композицию, иерархию, размерные пропорции, сценарии.

Не переносим: цвета (только токены), шрифты (self-hosted), emoji-иконки
(собственный SVG), `z-index` (шкала 0–4), keyframes (общие анимации),
инлайновые стили, Google Fonts.

## 5. Следующий шаг

1. `apps/web` — каркас на дизайн-токенах, self-hosted шрифты, шкала слоёв,
   focus-visible, reduced-motion, базовый набор SVG-иконок.
2. Первый экран: Editor Canvas V1 Floating Palette.
3. Затем: Project Page V6, Dashboard V1, Modules Library V7.

Обоснование по этапам 0–2 — в `docs/DECISIONS-CATALOG.md`.