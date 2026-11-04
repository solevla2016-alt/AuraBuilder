/**
 * Приветственная стартовая страница кабинета.
 *
 * Показывается над списком проектов и объясняет, что умеет конструктор:
 * человек, впервые вошедший в AuraBuilder, видит не пустую сетку карточек,
 * а короткий рассказ о возможностях и понятный первый шаг.
 *
 * Иллюстрация справа нарисована на CSS, а не картинкой: она наследует
 * цвета темы, не грузит лишний файл и не размывается на Retina.
 */

import { Icon, type IconName } from './icons';

interface Feature {
  icon: IconName;
  title: string;
  text: string;
}

const FEATURES: Feature[] = [
  {
    icon: 'cursor',
    title: 'Визуальный холст',
    text:
      'Перетаскивайте блоки, меняйте размеры и порядок. Сетка, направляющие и отмена действий — как в графическом редакторе.',
  },
  {
    icon: 'grid',
    title: 'Библиотека модулей',
    text:
      'Первый экран, преимущества, тарифы, формы, отзывы, каталог и подвал собираются из готовых смысловых блоков.',
  },
  {
    icon: 'data',
    title: 'Данные и формы',
    text:
      'Источники, записи и коллекции: заявка с сайта сразу становится данными проекта, без внешних таблиц и скриптов.',
  },
  {
    icon: 'flow',
    title: 'Логика без кода',
    text:
      'Триггеры, условия и действия: показывайте блоки по событию, обрабатывайте заявки и управляйте сценариями страницы.',
  },
  {
    icon: 'settings',
    title: 'Библиотека компонентов',
    text:
      'Единый стиль секций, текста и медиа. Свой цвет в формате #RRGGBB и автоматическая проверка контраста подписей.',
  },
  {
    icon: 'monitor',
    title: 'Адаптивность',
    text:
      'Один макет — три экрана. Проверяйте компьютер, планшет и телефон прямо в редакторе, не открывая вкладок.',
  },
  {
    icon: 'history',
    title: 'Версии и автосохранение',
    text:
      'Каждое изменение сохраняется само. История версий и защита от одновременной правки в двух вкладках.',
  },
  {
    icon: 'download',
    title: 'Публикация и экспорт',
    text:
      'Соберите статический пакет с HTML, CSS, sitemap и robots.txt и загрузите его на любой хостинг.',
  },
];

const STEPS = [
  {
    title: 'Создайте проект',
    text:
      'Назовите проект и откройте холст. Панель модулей, настройки и сохранение уже на месте.',
  },
  {
    title: 'Соберите страницу',
    text:
      'Добавляйте модули из палитры, меняйте тексты и стили, подключайте данные и логику.',
  },
  {
    title: 'Опубликуйте',
    text:
      'Проверьте компьютер, планшет и телефон, сохраните версию и выгрузите готовый сайт.',
  },
];

export function StartPage({
  projectCount,
  onCreate,
}: {
  /** Сколько проектов уже есть. null — список ещё загружается. */
  projectCount: number | null;
  /** «Создать проект»: открывает поле имени в блоке «Мои проекты». */
  onCreate: () => void;
}) {
  return (
    <>
      <section className="welcome" aria-labelledby="welcome-title">
        <div className="welcome__copy">
          <span className="welcome__eyebrow">
            Конструктор сайтов и веб-приложений
          </span>
          <h1 id="welcome-title" className="welcome__title">
            Сайт, который работает. Без единой строки кода
          </h1>
          <p className="welcome__lead">
            AuraBuilder — визуальный конструктор для лендингов, MVP и личных
            кабинетов. Соберите страницу из готовых блоков, подключите данные и
            логику, проверьте адаптивность и опубликуйте в один клик.
          </p>

          <div className="welcome__actions">
            <button
              type="button"
              className="btn btn--primary welcome__cta"
              onClick={onCreate}
            >
              <Icon name="plus" />
              {projectCount === 0 ? 'Создать первый проект' : 'Создать проект'}
            </button>
            <a className="btn btn--ghost" href="#features">
              Что умеет конструктор
              <Icon name="chevronDown" size={16} />
            </a>
          </div>

          <ul className="welcome__facts" aria-label="Коротко о конструкторе">
            <li>
              <b>0</b>
              <span>строк кода</span>
            </li>
            <li>
              <b>3</b>
              <span>режима предпросмотра</span>
            </li>
            <li>
              <b>1</b>
              <span>клик до публикации</span>
            </li>
          </ul>
        </div>

        {/* Декоративный макет: читать его нечего, поэтому hidden. */}
        <div className="welcome__preview" aria-hidden="true">
          <div className="welcome__window">
            <div className="welcome__window-bar">
              <span className="welcome__dot" />
              <span className="welcome__dot" />
              <span className="welcome__dot" />
              <span className="welcome__address">aurabuilder.site</span>
            </div>
            <div className="welcome__page">
              <div className="welcome__mini-nav">
                <span className="welcome__mini-logo" />
                <span className="welcome__mini-link" />
                <span className="welcome__mini-link" />
                <span className="welcome__mini-link" />
                <span className="welcome__mini-pill" />
              </div>
              <div className="welcome__mini-hero">
                <div className="welcome__mini-copy">
                  <span className="welcome__mini-kicker" />
                  <span className="welcome__mini-line welcome__mini-line--xl" />
                  <span className="welcome__mini-line welcome__mini-line--lg" />
                  <span className="welcome__mini-line" />
                  <span className="welcome__mini-line welcome__mini-line--sm" />
                  <span className="welcome__mini-button" />
                </div>
                <div className="welcome__mini-art">
                  <span className="welcome__mini-shape welcome__mini-shape--1" />
                  <span className="welcome__mini-shape welcome__mini-shape--2" />
                  <span className="welcome__mini-shape welcome__mini-shape--3" />
                </div>
              </div>
              <div className="welcome__mini-cards">
                <span />
                <span />
                <span />
              </div>
            </div>
          </div>

          <span className="welcome__chip welcome__chip--layers">
            <Icon name="layers" size={13} />
            Слои
          </span>
          <span className="welcome__chip welcome__chip--color">
            <i className="welcome__swatch" />
            #D9A441
          </span>
          <span className="welcome__chip welcome__chip--publish">
            <Icon name="rocket" size={13} />
            Опубликовано
          </span>
        </div>
      </section>

      <section
        className="welcome__section"
        id="features"
        aria-labelledby="features-title"
      >
        <header className="welcome__section-head">
          <span className="welcome__kicker">Возможности</span>
          <h2 id="features-title">Всё для запуска — в одном окне</h2>
          <p>
            Не нужно собирать стек из десятка сервисов: холст, контент, данные,
            логика и публикация уже связаны между собой.
          </p>
        </header>

        <ul className="welcome__features">
          {FEATURES.map((feature) => (
            <li key={feature.title} className="welcome__feature">
              <span className="welcome__icon" aria-hidden="true">
                <Icon name={feature.icon} size={20} />
              </span>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section
        className="welcome__section"
        aria-labelledby="steps-title"
      >
        <header className="welcome__section-head">
          <span className="welcome__kicker">Как это работает</span>
          <h2 id="steps-title">Три шага до запуска</h2>
        </header>

        <ol className="welcome__steps">
          {STEPS.map((step, index) => (
            <li key={step.title} className="welcome__step">
              <span className="welcome__step-num" aria-hidden="true">
                {index + 1}
              </span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
