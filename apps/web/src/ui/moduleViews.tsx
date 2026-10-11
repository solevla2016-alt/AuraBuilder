/**
 * Представления модулей для холста.
 *
 * Зачем это отдельный файл: до него каждый модуль рисовался одинаковым
 * прямоугольником с подписью. Редактор должен показывать макет
 * модуля, иначе нельзя ни оценить результат, ни отличить секцию от
 * кнопки — а именно это и делает подбор модуля осмысленным.
 *
 * Что здесь сознательно не делается:
 *
 * * Реальные изображения не загружаются. В блоке хранится путь или
 *   подпись, а файлов на стенде нет; плейсхолдер с названием медиа
 *   честнее картинки-заглушки, которая потом окажется не той.
 *
 * * Точная типографика не воспроизводится. Размеры текста приближены
 *   к макету и зависят от высоты блока: блок 40 пикселей высотой
 *   физически не вместит заголовок в 32 пикселя, и Konva не умеет
 *   подгонять текст под рамку без пересчёта вёрстки.
 *
 * * Данные в модулях data.* показаны пустыми каркасами. Узлы данных
 *   появляются на этапе 5 вместе с визуальной CMS, а в MVP (ТЗ п.12)
 *   эти блоки нужны как место сбора, а не как источник.
 */

import type { ReactNode } from 'react';
import { Circle, Group, Line, Rect, Text } from 'react-konva';
import type { Block } from './project';
import { cellText, type DataRecord } from './data';
import type { CanvasTokens } from './useCanvasTokens';
import { kindOf } from './moduleRegistry';
import type { ResolvedStyle } from './components';

/** Стили всех видов компонентов: ключ — вид блока. */
export type StyleByKind = Record<'section' | 'text' | 'media', ResolvedStyle>;

const FONT = 'Inter, sans-serif';
const MONO = "'JetBrains Mono', monospace";

/** Поля блока: одинаковые для всех модулей, как в макетах. */
const PAD = 20;

function prop(block: Block, name: string, fallback = ''): string {
  const value = block.props?.[name];
  return typeof value === 'string' && value.trim() !== '' ? value : fallback;
}

/** Текст блока: props предпочтительнее, иначе используется содержимое. */
function text(block: Block, propName: string, fallback: string): string {
  return prop(block, propName, block.content?.trim() || fallback);
}

/**
 * Кегль пропорционален высоте блока, но с потолком и полом.
 * Без этого текст в блоке 300 пикселей и в блоке 60 пикселей выглядел
 * бы одинаково, и пропорции макета переставали бы читаться.
 */
function fontFor(height: number, ratio: number, min: number, max: number): number {
  const size = Math.round(height * ratio);
  return Math.max(min, Math.min(max, size));
}

/**
 * Пункты многострочного свойства блока.
 *
 * Значение приходит строкой «Как оформить заказ?\nГде доставка?»,
 * а на холсте нужен список. Подсказки используются, когда свойство
 * не задано: пустая секция на макете не читается как секция, и
 * пользователь не понимает, что модуль вообще нарисован.
 */
function listProp(
  block: Block,
  name: string,
  count: number,
  fallback: string[],
): string[] {
  const raw = prop(block, name, '');
  if (!raw) return lines(fallback.join('\n'), count);
  // Разделителей два: перевод строки и точка с запятой. Второй нужен
  // для значения по умолчанию из схемы — оно записывается в одну
  // строку, перевода строки там не бывает.
  const parts = raw
    .split(/\r?\n/)
    .flatMap((chunk) => chunk.split(';'))
    .map((item) => item.trim())
    .filter(Boolean);
  return lines(parts.join('\n'), count);
}

function lines(content: string, count: number): string[] {
  const parts = content
    .split('\n')
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length >= count) return parts.slice(0, count);
  while (parts.length < count) parts.push(`Пункт ${parts.length + 1}`);
  return parts;
}

/** Прямоугольник-заглушка изображения с подписью. */
function mediaPlaceholder(
  block: Block,
  tokens: CanvasTokens,
  label: string,
  glyph: 'image' | 'play' | 'code',
) {
  return (
    <Group listening={false}>
      <Rect
        x={block.x + PAD}
        y={block.y + PAD}
        width={block.width - PAD * 2}
        height={block.height - PAD * 2}
        fill={tokens.panelSunken}
        stroke={tokens.border}
        strokeWidth={1}
        cornerRadius={8}
      />
      {glyph === 'play' ? (
        <>
          <Line
            points={[
              block.x + block.width / 2 - 14,
              block.y + block.height / 2 - 18,
              block.x + block.width / 2 + 20,
              block.y + block.height / 2,
              block.x + block.width / 2 - 14,
              block.y + block.height / 2 + 18,
            ]}
            closed
            fill={tokens.textSecondary}
          />
        </>
      ) : null}
      <Text
        x={block.x + block.width / 2 - 80}
        y={block.y + block.height / 2 + 14}
        width={160}
        align="center"
        text={label}
        fontSize={12}
        fontFamily={FONT}
        fill={tokens.textDisabled}
      />
    </Group>
  );
}



/**
 * Сетка колонок: основа секций feature, cards, footer и узлов данных.
 */
function columns(block: Block, count: number, gap = 16) {
  const width = (block.width - PAD * 2 - gap * (count - 1)) / count;
  return Array.from({ length: count }, (_, i) => ({
    x: block.x + PAD + i * (width + gap),
    y: block.y + PAD,
    width,
    height: block.height - PAD * 2,
  }));
}

/**
 * Ключи полей записи для подписи карточки.
 *
 * Холст не знает схему источника — её знает панель свойств, — поэтому
 * для блока data.field берётся явно указанный ключ, а для коллекции
 * поля читаются из первой записи: этого хватает для заголовка и двух
 * значений под ним.
 */
/**
 * Строки записей для показа: значения полей через разделитель.
 *
 * recordFields возвращает имена полей, а нужны сами значения: на
 * макете модулей вычислений видно, какие записи попадут в выгрузку.
 */
/** Строки многострочного свойства, ограниченные числом строк. */
function textLines(raw: string, count: number): string[] {
  const parts = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return parts.slice(0, count);
}

function recordLines(rows: DataRecord[]): string[] {
  return rows.map((row) =>
    Object.values(row.data ?? {})
      .filter((v) => v !== null && v !== '')
      .join(' \u00b7 '),
  );
}

function recordFields(block: Block, rows: DataRecord[]): string[] {
  const declared = block.props?.field;
  if (typeof declared === 'string' && declared !== '') return [declared];
  const first = rows[0]?.data;
  return first ? Object.keys(first).slice(0, 3) : [];
}

/**
 * Модули данных этапа 3.
 *
 * Показывают реальные записи выбранного источника. Если источник не
 * выбран или пуст, рисуется каркас с честной подписью: молча показать
 * пустые строки значило бы выглядеть так, будто данных нет из-за
 * ошибки, а не потому, что их ещё не ввели.
 */
function dataPlaceholder(
  block: Block,
  tokens: CanvasTokens,
  label: string,
  count: number,
  rows: DataRecord[],
): ReactNode {
  if (rows.length === 0) return dataEmpty(block, tokens, label);

  const visible = rows.slice(0, Math.max(1, count));
  const cols = columns(block, Math.min(visible.length, count), 12);
  const fields = recordFields(block, rows);
  // Колонок может оказаться меньше строк, если блок узкий: тогда
  // последняя колонка используется повторно, а не пропадает запись.
  // Если колонок нет вовсе (узкий блок), показываем каркас: делить на
  // ноль и рисовать NaN-координаты хуже, чем показать пустую сетку.
  const last = cols[cols.length - 1];
  if (!last) return dataEmpty(block, tokens, label);

  return (
    <Group listening={false}>
      {visible.map((row, i) => {
        const c = cols[i] ?? last;
        const title = cellText(row.data[fields[0] ?? '']);
        return (
          <Group key={row.id}>
            <Rect
              x={c.x}
              y={c.y}
              width={c.width}
              height={Math.max(48, c.height - 28)}
              fill={tokens.panel}
              stroke={tokens.border}
              strokeWidth={1}
              cornerRadius={8}
            />
            <Text
              x={c.x + 12}
              y={c.y + 14}
              width={c.width - 24}
              height={Math.max(0, c.height - 46)}
              text={title || 'Запись'}
              fontSize={13}
              fontStyle="bold"
              fontFamily={FONT}
              fill={tokens.textPrimary}
              ellipsis
            />
            {fields.slice(1, 3).map((field, j) => (
              <Text
                key={field}
                x={c.x + 12}
                y={c.y + 38 + j * 16}
                width={c.width - 24}
                text={cellText(row.data[field])}
                fontSize={12}
                fontFamily={FONT}
                fill={tokens.textSecondary}
                ellipsis
              />
            ))}
          </Group>
        );
      })}
    </Group>
  );
}

/** Каркас пустого узла данных: понятно, что данных ещё нет. */
function dataEmpty(block: Block, tokens: CanvasTokens, label: string): ReactNode {
  return (
    <Group listening={false}>
      <Rect
        x={block.x + PAD}
        y={block.y + PAD}
        width={block.width - PAD * 2}
        height={block.height - PAD * 2}
        fill={tokens.panelSunken}
        stroke={tokens.border}
        strokeWidth={1}
        strokeDashArray={[6, 4]}
        cornerRadius={8}
      />
      <Text
        x={block.x + PAD}
        y={block.y + block.height / 2 - 10}
        width={block.width - PAD * 2}
        align="center"
        text={label}
        fontSize={12}
        fontFamily={FONT}
        fill={tokens.textSecondary}
      />
      <Text
        x={block.x + PAD}
        y={block.y + block.height / 2 + 8}
        width={block.width - PAD * 2}
        align="center"
        text="выберите источник и добавьте записи в разделе «Данные»"
        fontSize={11}
        fontFamily={FONT}
        fill={tokens.textDisabled}
      />
    </Group>
  );
}

export function modulePreview(
  block: Block,
  tokens: CanvasTokens,
  records: DataRecord[] = [],
  styles?: StyleByKind,
): ReactNode {
  const h = block.height;
  const titleSize = fontFor(h, 0.13, 14, 30);
  const bodySize = fontFor(h, 0.06, 11, 15);

  /*
   * Стиль из библиотеки компонентов (ТЗ п.3.1).
   *
   * Стиль задаётся на вид компонента, а не на блок: цвет текста в
   * заголовке и в абзаце берётся из одного места, и правка в библиотеке
   * меняет их на всех страницах разом. Локальные свойства блока
   * (fontStyle из макета) сохраняются — библиотека меняет цвет и
   * насыщенность, а не ломает макет.
   */
  const style = styles?.[kindOf(block.module)];
  const headingFill = style?.text ?? tokens.textPrimary;
  const headingWeight = style?.weight && style.weight >= 600 ? 'bold' : 'normal';
  const bodyWeight = style?.weight && style.weight >= 600 ? 'bold' : 'normal';

  switch (block.module) {
    case 'section.hero': {
      const heading = text(block, 'heading', 'Заголовок первого экрана');
      const sub = prop(block, 'subheading', 'Подзаголовок объясняет, что это за страница');
      const button = prop(block, 'buttonLabel', 'Кнопка');
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
            wrap="word"
          />
          <Text
            x={block.x + PAD}
            y={block.y + PAD + titleSize + 10}
            width={(block.width - PAD * 2) * 0.8}
            text={sub}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
            wrap="word"
          />
          <Rect
            x={block.x + PAD}
            y={block.y + h - PAD - 34}
            width={Math.max(120, button.length * 9 + 32)}
            height={34}
            fill={tokens.selectionBorder}
            cornerRadius={8}
          />
          <Text
            x={block.x + PAD}
            y={block.y + h - PAD - 24}
            width={Math.max(120, button.length * 9 + 32)}
            align="center"
            text={button}
            fontSize={13}
            fontFamily={FONT}
            fill={tokens.canvas}
          />
        </Group>
      );
    }

    case 'section.header': {
      const items = ['Продукты', 'Услуги', 'Контакты'];
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + 12}
            text="Логотип"
            fontSize={14}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {items.map((item, i) => (
            <Text
              key={item}
              x={block.x + block.width - PAD - 200 + i * 70}
              y={block.y + 15}
              text={item}
              fontSize={12}
              fontFamily={FONT}
              fill={tokens.textSecondary}
            />
          ))}
          <Line
            points={[block.x, block.y + h - 6, block.x + block.width, block.y + h - 6]}
            stroke={tokens.border}
            strokeWidth={1}
          />
        </Group>
      );
    }

    case 'section.feature': {
      const cols = columns(block, 3);
      const titles = ['Скорость', 'Надёжность', 'Поддержка'];
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text="Почему это работает"
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {cols.map((c, i) => (
            <Group key={`${block.id}-f${i}`}>
              <Rect
                x={c.x}
                y={block.y + PAD + titleSize + 12}
                width={c.width}
                height={Math.max(24, h - PAD * 2 - titleSize - 12)}
                fill={tokens.canvas}
                stroke={tokens.border}
                strokeWidth={1}
                cornerRadius={8}
              />
              <Text
                x={c.x + 14}
                y={block.y + PAD + titleSize + 26}
                width={c.width - 28}
                text={titles[i] ?? 'Преимущество'}
                fontSize={bodySize}
                fontStyle="bold"
                fontFamily={FONT}
                fill={tokens.textPrimary}
              />
              <Text
                x={c.x + 14}
                y={block.y + PAD + titleSize + 26 + bodySize + 6}
                width={c.width - 28}
                text="Короткое объяснение, чем эта часть полезна."
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textSecondary}
                wrap="word"
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'section.cards': {
      const cols = columns(block, 3);
      const titles = ['Карточка один', 'Карточка два', 'Карточка три'];
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={text(block, 'heading', 'Подборка')}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {cols.map((c, i) => (
            <Group key={`${block.id}-c${i}`}>
              <Rect
                x={c.x}
                y={block.y + PAD + titleSize + 12}
                width={c.width}
                height={Math.max(30, h - PAD * 2 - titleSize - 12)}
                fill={tokens.panel}
                stroke={tokens.border}
                strokeWidth={1}
                cornerRadius={10}
              />
              <Rect
                x={c.x}
                y={block.y + PAD + titleSize + 12}
                width={c.width}
                height={Math.max(30, (h - PAD * 2 - titleSize - 12) * 0.45)}
                fill={tokens.panelSunken}
                cornerRadius={[10, 10, 0, 0]}
              />
              <Text
                x={c.x + 14}
                y={block.y + PAD + titleSize + 24 + (h - PAD * 2 - titleSize - 12) * 0.45}
                width={c.width - 28}
                text={titles[i] ?? 'Карточка'}
                fontSize={bodySize}
                fontStyle="bold"
                fontFamily={FONT}
                fill={tokens.textPrimary}
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'section.split': {
      const half = (block.width - PAD * 2 - 24) / 2;
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={half}
            text={text(block, 'heading', 'Левая колонка')}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
            wrap="word"
          />
          <Text
            x={block.x + PAD}
            y={block.y + PAD + titleSize + 10}
            width={half}
            height={Math.max(0, h - PAD * 2 - titleSize - 10)}
            text={block.content?.trim() || 'Текст описания рядом с изображением.'}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
            wrap="word"
            ellipsis
          />
          <Rect
            x={block.x + PAD + half + 24}
            y={block.y + PAD}
            width={half}
            height={h - PAD * 2}
            fill={tokens.panelSunken}
            stroke={tokens.border}
            strokeWidth={1}
            cornerRadius={8}
          />
        </Group>
      );
    }

    case 'section.cta': {
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={text(block, 'heading', 'Остались вопросы?')}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
            wrap="word"
          />
          <Rect
            x={block.x + PAD}
            y={block.y + h - PAD - 34}
            width={150}
            height={34}
            fill={tokens.selectionBorder}
            cornerRadius={8}
          />
          <Text
            x={block.x + PAD}
            y={block.y + h - PAD - 24}
            width={150}
            align="center"
            text={prop(block, 'buttonLabel', 'Связаться')}
            fontSize={13}
            fontFamily={FONT}
            fill={tokens.canvas}
          />
        </Group>
      );
    }

    case 'section.footer': {
      const cols = columns(block, 3);
      const titles = ['Продукты', 'Компания', 'Контакты'];
      return (
        <Group listening={false}>
          {cols.map((c, i) => (
            <Group key={`${block.id}-ftr${i}`}>
              <Text
                x={c.x}
                y={block.y + PAD}
                width={c.width}
                text={titles[i] ?? 'Колонка'}
                fontSize={bodySize}
                fontStyle="bold"
                fontFamily={FONT}
                fill={tokens.textPrimary}
              />
              <Text
                x={c.x}
                y={block.y + PAD + bodySize + 8}
                width={c.width}
                height={Math.max(0, h - PAD * 2 - bodySize - 8)}
                text={lines('Пункт меню\nЕщё пункт\nТретий пункт', 3).join('\n')}
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textSecondary}
                lineHeight={1.6}
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'section.spacer': {
      return (
        <Group listening={false}>
          <Line
            points={[
              block.x + block.width / 2 - 40,
              block.y + h / 2,
              block.x + block.width / 2 + 40,
              block.y + h / 2,
            ]}
            stroke={tokens.guideLine}
            strokeWidth={2}
            lineCap="round"
          />
          <Text
            x={block.x}
            y={block.y + h / 2 + 12}
            width={block.width}
            align="center"
            text={`отступ ${Math.round(h)} px`}
            fontSize={11}
            fontFamily={FONT}
            fill={tokens.textDisabled}
          />
        </Group>
      );
    }

    case 'text.heading': {
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y}
            width={block.width - PAD * 2}
            height={h}
            verticalAlign="middle"
            text={text(block, 'text', block.label)}
            fontSize={fontFor(h, 0.32, 16, 34)}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
            wrap="word"
            ellipsis
          />
        </Group>
      );
    }

    case 'text.paragraph': {
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y}
            width={block.width - PAD * 2}
            height={h}
            verticalAlign="middle"
            text={text(
              block,
              'text',
              'Текст абзаца. Он показывает, как будет выглядеть содержимое блока на собранной странице.',
            )}
            fontSize={fontFor(h, 0.07, 12, 16)}
            fontStyle={bodyWeight}
            fontFamily={FONT}
            fill={headingFill}
            lineHeight={1.6}
            wrap="word"
            ellipsis
          />
        </Group>
      );
    }

    case 'text.list': {
      const items = lines(block.content?.trim() || 'Первый пункт\nВторой пункт\nТретий пункт', 3);
      return (
        <Group listening={false}>
          {items.map((item, i) => (
            <Group key={`${block.id}-li${i}`}>
              <Rect
                x={block.x + PAD}
                y={block.y + PAD + i * ((h - PAD * 2) / items.length) + 5}
                width={5}
                height={5}
                fill={tokens.textSecondary}
                cornerRadius={2}
              />
              <Text
                x={block.x + PAD + 16}
                y={block.y + PAD + i * ((h - PAD * 2) / items.length)}
                width={block.width - PAD * 2 - 16}
                height={(h - PAD * 2) / items.length}
                verticalAlign="middle"
                text={item}
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textPrimary}
                ellipsis
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'text.quote': {
      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={block.y + 8}
            width={3}
            height={h - 16}
            fill={tokens.selectionBorder}
            cornerRadius={2}
          />
          <Text
            x={block.x + PAD + 16}
            y={block.y + 8}
            width={block.width - PAD * 2 - 16}
            height={h - 16}
            verticalAlign="middle"
            text={text(block, 'text', 'Цитата, которая объясняет решение')}
            fontSize={fontFor(h, 0.09, 13, 18)}
            fontStyle="italic"
            fontFamily={FONT}
            fill={tokens.textPrimary}
            wrap="word"
            ellipsis
          />
        </Group>
      );
    }

    case 'media.image':
      return mediaPlaceholder(block, tokens, 'Изображение', 'image');
    case 'media.video':
      return mediaPlaceholder(block, tokens, 'Видео', 'play');
    case 'media.embed':
      return mediaPlaceholder(block, tokens, 'Встраивание: карта, виджет, iframe', 'code');

    case 'action.button': {
      const label = text(block, 'label', block.label);
      const width = Math.max(110, label.length * 8 + 32);
      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={block.y + (h - 36) / 2}
            width={width}
            height={36}
            fill={tokens.selectionBorder}
            cornerRadius={8}
          />
          <Text
            x={block.x + PAD}
            y={block.y + (h - 36) / 2 + 10}
            width={width}
            align="center"
            text={label}
            fontSize={13}
            fontFamily={FONT}
            fill={tokens.canvas}
          />
        </Group>
      );
    }

    case 'action.link': {
      const label = text(block, 'label', block.label);
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y}
            width={block.width - PAD * 2}
            height={h}
            verticalAlign="middle"
            text={label}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textPrimary}
            decoration="underline"
            ellipsis
          />
        </Group>
      );
    }

    case 'action.form': {
      const fieldWidth = (block.width - PAD * 2 - 12) / 2;
      return (
        <Group listening={false}>
          {[0, 1].map((i) => (
            <Group key={`${block.id}-field${i}`}>
              <Text
                x={block.x + PAD + i * (fieldWidth + 12)}
                y={block.y + PAD}
                text={i === 0 ? 'Имя' : 'Телефон'}
                fontSize={12}
                fontFamily={FONT}
                fill={tokens.textSecondary}
              />
              <Rect
                x={block.x + PAD + i * (fieldWidth + 12)}
                y={block.y + PAD + 20}
                width={fieldWidth}
                height={36}
                fill={tokens.canvas}
                stroke={tokens.border}
                strokeWidth={1}
                cornerRadius={8}
              />
            </Group>
          ))}
          <Rect
            x={block.x + PAD}
            y={block.y + PAD + 72}
            width={140}
            height={36}
            fill={tokens.selectionBorder}
            cornerRadius={8}
          />
          <Text
            x={block.x + PAD}
            y={block.y + PAD + 82}
            width={140}
            align="center"
            text="Отправить"
            fontSize={13}
            fontFamily={FONT}
            fill={tokens.canvas}
          />
        </Group>
      );
    }

    case 'nav.breadcrumb': {
      const items = ['Главная', 'Раздел', 'Страница'];
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y}
            width={block.width - PAD * 2}
            height={h}
            verticalAlign="middle"
            text={items.join('  /  ')}
            fontSize={12}
            fontFamily={FONT}
            fill={tokens.textSecondary}
          />
        </Group>
      );
    }

    case 'seo.schema':
    case 'code.custom': {
      const snippet =
        block.module === 'seo.schema'
          ? '{\n  "@context": "https://schema.org",\n  "@type": "Product"\n}'
          : '<!-- произвольный код в iframe-песочнице -->';
      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={block.y + 8}
            width={block.width - PAD * 2}
            height={h - 16}
            fill={tokens.panelSunken}
            stroke={tokens.border}
            strokeWidth={1}
            cornerRadius={8}
          />
          <Text
            x={block.x + PAD + 12}
            y={block.y + 16}
            width={block.width - PAD * 2 - 24}
            height={h - 32}
            text={snippet}
            fontSize={11}
            fontFamily={MONO}
            fill={tokens.textSecondary}
            wrap="word"
            ellipsis
          />
        </Group>
      );
    }

    case 'data.collection': {
      const limit = Number(block.props?.limit ?? 6) || 6;
      return dataPlaceholder(block, tokens, 'Коллекция записей', limit, records);
    }
    case 'data.list': {
      const limit = Number(block.props?.limit ?? 10) || 10;
      return dataPlaceholder(block, tokens, 'Список записей', limit, records);
    }
    case 'data.single':
      return dataPlaceholder(block, tokens, 'Одна запись', 1, records);
    case 'data.field': {
      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y}
            width={(block.width - PAD * 2) * 0.4}
            height={h}
            verticalAlign="middle"
            text={text(block, 'label', 'Поле')}
            fontSize={12}
            fontFamily={FONT}
            fill={tokens.textSecondary}
          />
          <Text
            x={block.x + PAD + (block.width - PAD * 2) * 0.4}
            y={block.y}
            width={(block.width - PAD * 2) * 0.6}
            height={h}
            verticalAlign="middle"
            text={text(block, 'text', 'значение')}
            fontSize={13}
            fontFamily={FONT}
            fill={tokens.textPrimary}
            ellipsis
          />
        </Group>
      );
    }
    case 'data.search': {
      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={block.y + (h - 36) / 2}
            width={block.width - PAD * 2}
            height={36}
            fill={tokens.canvas}
            stroke={tokens.border}
            strokeWidth={1}
            cornerRadius={18}
          />
          <Text
            x={block.x + PAD + 16}
            y={block.y + (h - 36) / 2 + 10}
            text="Поиск по узлу данных"
            fontSize={12}
            fontFamily={FONT}
            fill={tokens.textDisabled}
          />
        </Group>
      );
    }
    case 'data.pagination': {
      // Подписи страниц выводятся вторым проходом: в Konva нет
      // вложенного текста, поэтому прямоугольник и его подпись —
      // два узла, и они обязаны совпадать по координатам.
      const pages = ['1', '2', '3'];
      return (
        <Group listening={false}>
          {pages.map((_, i) => (
            <Rect
              key={`${block.id}-p${i}`}
              x={block.x + PAD + i * 44}
              y={block.y + (h - 32) / 2}
              width={32}
              height={32}
              fill={i === 0 ? tokens.selectionBorder : tokens.canvas}
              stroke={tokens.border}
              strokeWidth={1}
              cornerRadius={8}
            />
          ))}
          {pages.map((page, i) => (
            <Text
              key={`${block.id}-pt${i}`}
              x={block.x + PAD + i * 44}
              y={block.y + (h - 32) / 2 + 9}
              width={32}
              align="center"
              text={page}
              fontSize={12}
              fontFamily={FONT}
              fill={i === 0 ? tokens.canvas : tokens.textSecondary}
            />
          ))}
        </Group>
      );
    }

    case 'section.accordion': {
      /*
       * Аккордеон. Пункты идут полосами во всю ширину секции, а не
       * колонками: раскрытая панель занимает всю ширину, и колонки
       * разорвали бы её на части. Первый пункт показан раскрытым
       * (firstOpen), остальные свернуты — иначе на макете не видно,
       * где происходит раскрытие.
       */
      const heading = prop(block, 'heading', 'Частые вопросы');
      const items = listProp(block, 'items', 4, ['Как оформить заказ?', 'Где доставка?', 'Как вернуть?']);
      const firstOpen = block.props?.['firstOpen'] !== false;
      const top = block.y + PAD + titleSize + 10;
      const available = h - PAD * 2 - titleSize - 10;
      const rowHeight = Math.max(26, available / Math.max(items.length, 1));

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {items.map((item, i) => (
            <Group key={`${block.id}-a${i}`}>
              {firstOpen && i === 0 ? (
                <Rect
                  x={block.x + PAD}
                  y={top + i * rowHeight}
                  width={block.width - PAD * 2}
                  height={rowHeight}
                  fill={tokens.panelSunken}
                  cornerRadius={8}
                />
              ) : null}
              <Text
                x={block.x + PAD + 14}
                y={top + i * rowHeight + rowHeight / 2 - 9}
                width={block.width - PAD * 2 - 40}
                text={item}
                fontSize={bodySize}
                fontStyle="bold"
                fontFamily={FONT}
                fill={tokens.textPrimary}
              />
              {/* Маркер раскрытия: у первого пункта стрелка вверх. */}
              <Line
                points={[
                  block.x + block.width - PAD - 22,
                  top + i * rowHeight + rowHeight / 2 - (firstOpen && i === 0 ? 4 : 0),
                  block.x + block.width - PAD - 16,
                  top + i * rowHeight + rowHeight / 2 + (firstOpen && i === 0 ? 0 : 4),
                  block.x + block.width - PAD - 10,
                  top + i * rowHeight + rowHeight / 2 - (firstOpen && i === 0 ? 4 : 0),
                ]}
                stroke={tokens.textSecondary}
                strokeWidth={1.5}
                lineCap="round"
                lineJoin="round"
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'section.tabs': {
      /*
       * Вкладки. Панель подписей идёт на всю ширину, активная
       * подчёркнута акцентом — это единственный признак, который
       * отличает вкладки от обычного списка текста.
       */
      const heading = prop(block, 'heading', 'Как это работает');
      const tabs = listProp(block, 'tabs', 3, ['Подготовка', 'Проверка', 'Доставка']);
      const count = Math.min(tabs.length, Math.max(2, Number(block.props?.['columns'] ?? 3)));
      const shown = tabs.slice(0, count);
      const tabWidth = (block.width - PAD * 2) / Math.max(shown.length, 1);
      const top = block.y + PAD + titleSize + 10;

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {shown.map((tab, i) => (
            <Group key={`${block.id}-t${i}`}>
              <Text
                x={block.x + PAD + i * tabWidth}
                y={top}
                width={tabWidth}
                align="center"
                text={tab}
                fontSize={bodySize}
                fontStyle={i === 0 ? 'bold' : 'normal'}
                fontFamily={FONT}
                fill={i === 0 ? tokens.textPrimary : tokens.textSecondary}
              />
              {i === 0 ? (
                <Line
                  points={[
                    block.x + PAD + i * tabWidth + 8,
                    top + titleSize + 4,
                    block.x + PAD + (i + 1) * tabWidth - 8,
                    top + titleSize + 4,
                  ]}
                  stroke={tokens.selectionBorder}
                  strokeWidth={2}
                  lineCap="round"
                />
              ) : null}
            </Group>
          ))}
          <Rect
            x={block.x + PAD}
            y={top + titleSize + 6}
            width={block.width - PAD * 2}
            height={1}
            fill={tokens.border}
          />
          {/* Содержимое активной вкладки — один абзац, а не полный
              макет: содержимое вкладок задаётся данными, а на холсте
              важнее показать, что вкладок несколько и одна выбрана. */}
          <Text
            x={block.x + PAD}
            y={top + titleSize + 22}
            width={block.width - PAD * 2}
            height={Math.max(20, h - PAD * 2 - titleSize - 32)}
            text={prop(block, 'content', 'Содержимое выбранной вкладки')}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
            wrap="word"
            ellipsis
          />
        </Group>
      );
    }

    case 'section.gallery': {
      /*
       * Галерея. Сетка из плейсхолдеров: файлов на стенде нет, и
       * рамка с подписью честнее картинки-заглушки, которая потом
       * окажется не той.
       */
      const heading = prop(block, 'heading', 'Работы');
      const columns = Math.max(2, Math.min(5, Number(block.props?.['columns'] ?? 3)));
      const gap = Math.max(4, Math.min(48, Number(block.props?.['gap'] ?? 16)));
      const top = block.y + PAD + titleSize + 10;
      const area = Math.max(40, h - PAD * 2 - titleSize - 10);
      const frames = Math.max(columns, Math.min(10, Number(block.props?.['frames'] ?? columns)));
      const rows = Math.ceil(frames / columns);
      const cellW = (block.width - PAD * 2 - gap * (columns - 1)) / columns;
      const cellH = (area - gap * (rows - 1)) / rows;

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {Array.from({ length: frames }, (_, i) => {
            const col = i % columns;
            const row = Math.floor(i / columns);
            const x = block.x + PAD + col * (cellW + gap);
            const y = top + row * (cellH + gap);
            return (
              <Group key={`${block.id}-g${i}`}>
                <Rect
                  x={x}
                  y={y}
                  width={cellW}
                  height={cellH}
                  fill={tokens.panelSunken}
                  stroke={tokens.border}
                  strokeWidth={1}
                  cornerRadius={8}
                />
                <Text
                  x={x + 10}
                  y={y + cellH / 2 - 7}
                  width={cellW - 20}
                  align="center"
                  text={`${i + 1}`}
                  fontSize={bodySize}
                  fontFamily={MONO}
                  fill={tokens.textSecondary}
                />
              </Group>
            );
          })}
        </Group>
      );
    }

    case 'section.timeline': {
      /*
       * Таймлайн. Вертикальная линия с точками: главный признак —
       * события идут во времени, и без линии список дат читался бы
       * как обычный текст.
       */
      const heading = prop(block, 'heading', 'История');
      const events = Math.max(2, Math.min(8, Number(block.props?.['events'] ?? 4)));
      const year = Number(block.props?.['year'] ?? 2019);
      const stepYears = Math.max(1, Number(block.props?.['stepYears'] ?? 2));
      const top = block.y + PAD + titleSize + 12;
      const step = (h - PAD * 2 - titleSize - 12) / Math.max(events, 1);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          <Line
            points={[block.x + PAD + 7, top, block.x + PAD + 7, top + step * (events - 1)]}
            stroke={tokens.border}
            strokeWidth={2}
            lineCap="round"
          />
          {Array.from({ length: events }, (_, i) => (
            <Group key={`${block.id}-e${i}`}>
              <Circle
                x={block.x + PAD + 7}
                y={top + i * step}
                radius={5}
                fill={i === 0 ? tokens.selectionBorder : tokens.panel}
                stroke={tokens.selectionBorder}
                strokeWidth={1.5}
              />
              <Text
                x={block.x + PAD + 24}
                y={top + i * step - 8}
                width={90}
                text={String(year + stepYears * i)}
                fontSize={bodySize}
                fontStyle="bold"
                fontFamily={MONO}
                fill={tokens.selectionBorder}
              />
              <Text
                x={block.x + PAD + 118}
                y={top + i * step - 8}
                width={block.width - PAD * 2 - 118}
                text={prop(block, `event${i}`, 'Событие')}
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textPrimary}
                wrap="word"
                ellipsis
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'section.steps': {
      /*
       * Шаги. Кружки с номерами и соединительная линия: без неё это
       * просто строка текста, а с ней виден порядок.
       */
      const heading = prop(block, 'heading', 'Три шага');
      const steps = listProp(block, 'steps', 3, ['Заявка', 'Согласование', 'Работа']);
      const showNumbers = block.props?.['showNumbers'] !== false;
      const top = block.y + PAD + titleSize + 18;
      const stepW = (block.width - PAD * 2) / Math.max(steps.length, 1);
      const radius = 15;
      const midY = top + radius;

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {steps.length > 1 ? (
            <Line
              points={[
                block.x + PAD + stepW / 2,
                midY,
                block.x + block.width - PAD - stepW / 2,
                midY,
              ]}
              stroke={tokens.border}
              strokeWidth={2}
              strokeDash={[6, 6]}
            />
          ) : null}
          {steps.map((step, i) => (
            <Group key={`${block.id}-s${i}`}>
              <Circle
                x={block.x + PAD + stepW / 2 + i * stepW}
                y={midY}
                radius={radius}
                fill={i === 0 ? tokens.selectionBorder : tokens.panel}
                stroke={tokens.selectionBorder}
                strokeWidth={1.5}
              />
              {showNumbers ? (
                <Text
                  x={block.x + PAD + i * stepW + stepW / 2 - radius}
                  y={midY - 7}
                  width={radius * 2}
                  align="center"
                  text={String(i + 1)}
                  fontSize={bodySize}
                  fontStyle="bold"
                  fontFamily={MONO}
                  fill={i === 0 ? tokens.canvas : tokens.textPrimary}
                />
              ) : null}
              <Text
                x={block.x + PAD + i * stepW + 6}
                y={midY + radius + 10}
                width={stepW - 12}
                align="center"
                text={step}
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textPrimary}
                wrap="word"
                ellipsis
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'legal.offer':
    case 'legal.policy': {
      /*
       * Документ: заголовок, дата редакции и полотно текста.
       *
       * Дата показана отдельно от заголовка, потому что для юридического
       * документа это существенная часть: по дате видно, какая редакция
       * опубликована, и она должна попасть в выгрузку вместе с текстом.
       */
      const heading = prop(block, 'heading', 'Публичная оферта');
      const updated = prop(block, 'updated', '') ?? '';
      const body = prop(block, 'body', 'Текст документа размещается здесь.');
      const top = block.y + PAD + titleSize + (updated ? 8 : 0);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {updated ? (
            <Text
              x={block.x + PAD}
              y={block.y + PAD + titleSize}
              width={block.width - PAD * 2}
              text={`Редакция от ${updated}`}
              fontSize={bodySize}
              fontFamily={MONO}
              fill={tokens.textSecondary}
            />
          ) : null}
          <Rect
            x={block.x + PAD}
            y={top + titleSize + (updated ? 8 : 0)}
            width={block.width - PAD * 2}
            height={Math.max(30, h - PAD * 2 - titleSize - (updated ? 8 : 0))}
            fill={tokens.panel}
            stroke={tokens.border}
            strokeWidth={1}
            cornerRadius={8}
          />
          <Text
            x={block.x + PAD + 14}
            y={top + titleSize + (updated ? 8 : 0) + 12}
            width={block.width - PAD * 2 - 28}
            height={Math.max(20, h - PAD * 2 - titleSize - 40)}
            text={body}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textPrimary}
            wrap="word"
            ellipsis
          />
        </Group>
      );
    }

    case 'legal.requisites': {
      /*
       * Реквизиты строкой по полям: ИНН, ОГРН и адрес должны читаться
       * подряд, а не прятаться в абзац — их проверяют при закупке.
       */
      const heading = prop(block, 'heading', 'Реквизиты');
      const rows = ([
        ['Наименование', prop(block, 'name', 'Наименование организации')],
        ['ИНН', prop(block, 'inn', '0000000000')],
        ['ОГРН', prop(block, 'ogrn', '')],
        ['Адрес', prop(block, 'address', 'Адрес')],
        ['Почта', prop(block, 'email', '')],
      ] as [string, string | undefined][]).filter(
        (pair): pair is [string, string] => Boolean(pair[1]),
      );
      const top = block.y + PAD + titleSize + 10;
      const rowHeight = Math.max(18, (h - PAD * 2 - titleSize - 10) / rows.length);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {rows.map(([label, value], i) => (
            <Group key={`${block.id}-r${i}`}>
              <Text
                x={block.x + PAD}
                y={top + i * rowHeight}
                width={120}
                text={label}
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textSecondary}
              />
              <Text
                x={block.x + PAD + 124}
                y={top + i * rowHeight}
                width={block.width - PAD * 2 - 124}
                text={value}
                fontSize={bodySize}
                fontStyle={label === 'ИНН' || label === 'ОГРН' ? 'bold' : 'normal'}
                fontFamily={label === 'ИНН' || label === 'ОГРН' ? MONO : FONT}
                fill={tokens.textPrimary}
                wrap="word"
                ellipsis
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'legal.consent': {
      /*
       * Согласие: флажок и текст рядом. Неактивное состояние флажка
       * нарисовано рамкой, а не галочкой — форма отправляет данные
       * только с отмеченным флажком, и на макете это должно быть видно.
       */
      const text = prop(block, 'text', 'Я согласен на обработку персональных данных');
      const size = 16;
      const midY = block.y + h / 2 - size / 2;

      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={midY}
            width={size}
            height={size}
            fill={tokens.panel}
            stroke={tokens.textSecondary}
            strokeWidth={1.5}
            cornerRadius={3}
          />
          <Text
            x={block.x + PAD + size + 10}
            y={midY + 1}
            width={block.width - PAD * 2 - size - 10}
            height={h - PAD}
            text={text}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textPrimary}
            wrap="word"
            ellipsis
          />
        </Group>
      );
    }

    case 'legal.age-mark': {
      /*
       * Возрастная маркировка: знак «18+» в рамке и пояснение.
       * Рамка обязательна — по ТЗ п.9.6 маркировка должна быть явно
       * читаемой, а не просто набором цифр в тексте.
       */
      const text = prop(block, 'text', '18+');
      const note = prop(block, 'note', '') ?? '';
      const boxSize = Math.min(56, h - PAD * 2);
      const midY = block.y + h / 2 - (note ? boxSize + 8 : 0) / 2;

      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={midY}
            width={boxSize}
            height={boxSize}
            stroke={tokens.textPrimary}
            strokeWidth={2}
            cornerRadius={6}
          />
          <Text
            x={block.x + PAD}
            y={midY + boxSize / 2 - 13}
            width={boxSize}
            align="center"
            text={text}
            fontSize={Math.min(22, boxSize * 0.44)}
            fontStyle="bold"
            fontFamily={MONO}
            fill={tokens.textPrimary}
          />
          {note ? (
            <Text
              x={block.x + PAD}
              y={midY + boxSize + 6}
              width={block.width - PAD * 2}
              text={note}
              fontSize={bodySize}
              fontFamily={FONT}
              fill={tokens.textSecondary}
              wrap="word"
              ellipsis
            />
          ) : null}
        </Group>
      );
    }

    case 'legal.ad-mark': {
      /*
       * Маркировка рекламы: рамка вокруг пометки. По ТЗ п.9.5 пометка
       * должна отделяться от контента, иначе её невозможно отличить от
       * обычной подписи.
       */
      const text = prop(block, 'text', 'Реклама');
      const href = prop(block, 'href', '') ?? '';
      const label = prop(block, 'label', '') ?? '';
      const boxHeight = 34;
      const boxWidth = Math.min(block.width - PAD * 2, Math.max(120, text.length * 9 + 40));

      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={block.y + h / 2 - boxHeight / 2}
            width={boxWidth}
            height={boxHeight}
            fill={tokens.panelSunken}
            stroke={tokens.border}
            strokeWidth={1}
            cornerRadius={6}
          />
          <Text
            x={block.x + PAD + 12}
            y={block.y + h / 2 - 9}
            width={boxWidth - 24}
            text={href && label ? `${text} · ${label}` : text}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
          />
        </Group>
      );
    }

    case 'trust.logos': {
      /*
       * Логотипы клиентов. Плейсхолдеры с подписями: файлов на стенде
       * нет, а рамка с названием честнее подменённой картинки.
       */
      const heading = prop(block, 'heading', 'Нам доверяют');
      const items = listProp(block, 'items', 4, ['Клиент', 'Клиент', 'Клиент']);
      const muted = block.props?.['grayscale'] !== false;
      const top = block.y + PAD + titleSize + 10;
      const area = Math.max(30, h - PAD * 2 - titleSize - 10);
      const cellW = (block.width - PAD * 2 - 12 * (items.length - 1)) / Math.max(items.length, 1);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {items.map((item, i) => (
            <Group key={`${block.id}-l${i}`}>
              <Rect
                x={block.x + PAD + i * (cellW + 12)}
                y={top}
                width={cellW}
                height={area}
                fill={tokens.panelSunken}
                stroke={tokens.border}
                strokeWidth={1}
                cornerRadius={8}
              />
              <Text
                x={block.x + PAD + i * (cellW + 12) + 8}
                y={top + area / 2 - 8}
                width={cellW - 16}
                align="center"
                text={item}
                fontSize={bodySize}
                fontFamily={FONT}
                fill={muted ? tokens.textSecondary : tokens.textPrimary}
                ellipsis
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'trust.review': {
      /*
       * Отзыв: оценка звёздами, текст и автор. Звёзды рисуются
       * символами, а не иконками: их видно на любом масштабе холста и
       * в выгрузке без шрифтовых файлов.
       */
      const author = prop(block, 'author', 'Покупатель');
      const rating = Math.max(1, Math.min(5, Number(block.props?.['rating'] ?? 5)));
      const body = prop(block, 'text', 'Отзыв покупателя о работе магазина.');
      const top = block.y + PAD;

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={top}
            width={block.width - PAD * 2}
            text={'★'.repeat(rating) + '☆'.repeat(5 - rating)}
            fontSize={Math.min(18, titleSize * 0.8)}
            fontFamily={FONT}
            fill={tokens.selectionBorder}
          />
          <Text
            x={block.x + PAD}
            y={top + 26}
            width={block.width - PAD * 2}
            height={Math.max(20, h - PAD * 2 - 52)}
            text={body}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textPrimary}
            wrap="word"
            ellipsis
          />
          <Text
            x={block.x + PAD}
            y={block.y + h - PAD - 14}
            width={block.width - PAD * 2}
            text={author}
            fontSize={bodySize}
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textSecondary}
          />
        </Group>
      );
    }

    case 'trust.rating': {
      /*
       * Рейтинг: крупная оценка, число отзывов и, если задан,
       * источник. Оценка набрана моноширинным шрифтом — рядом стоящие
       * цифры в обычном шрифте разъезжаются.
       */
      const value = prop(block, 'value', '4.8') ?? '4.8';
      const count = prop(block, 'count', '120') ?? '120';
      const source = prop(block, 'source', '') ?? '';
      const rating = Math.max(0, Math.min(5, Number(value) || 0));
      const stars = '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + h / 2 - titleSize / 2 - 8}
            width={120}
            text={value}
            fontSize={Math.max(28, titleSize * 1.4)}
            fontStyle="bold"
            fontFamily={MONO}
            fill={tokens.selectionBorder}
          />
          <Text
            x={block.x + PAD + 124}
            y={block.y + h / 2 - 22}
            width={block.width - PAD * 2 - 124}
            text={stars}
            fontSize={Math.min(16, bodySize)}
            fontFamily={FONT}
            fill={tokens.selectionBorder}
          />
          <Text
            x={block.x + PAD + 124}
            y={block.y + h / 2 - 2}
            width={block.width - PAD * 2 - 124}
            text={`${count} отзывов${source ? ` · ${source}` : ''}`}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
            ellipsis
          />
        </Group>
      );
    }

    case 'data.count': {
      /*
       * Счётчик: крупное число и подпись под ним. Число моноширинным
       * шрифтом — иначе соседние разряды разъезжаются, а на макете
       * это заметно сильнее, чем в обычном тексте.
       */
      const label = prop(block, 'label', 'Всего');
      const count = records.length;

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + h / 2 - titleSize}
            width={block.width - PAD * 2}
            align="center"
            text={String(count)}
            fontSize={Math.max(32, titleSize * 1.6)}
            fontStyle="bold"
            fontFamily={MONO}
            fill={tokens.selectionBorder}
          />
          <Text
            x={block.x + PAD}
            y={block.y + h / 2 + titleSize * 0.7}
            width={block.width - PAD * 2}
            align="center"
            text={label}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
          />
        </Group>
      );
    }

    case 'data.aggregate': {
      /*
       * Итог: подпись и значение. Значение вычисляется на сервере при
       * сборке, поэтому на холсте показывается то, что приедет в
       * выгрузку, а не пересчёт в браузере.
       */
      const label = prop(block, 'label', 'Итого');
      const suffix = prop(block, 'suffix', '');

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + h / 2 - bodySize / 2 - 8}
            width={block.width - PAD * 2}
            text={label}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
          />
          <Text
            x={block.x + PAD}
            y={block.y + h / 2 + 4}
            width={block.width - PAD * 2}
            text={prop(block, 'preview', '—')}
            fontSize={Math.max(24, titleSize)}
            fontStyle="bold"
            fontFamily={MONO}
            fill={tokens.textPrimary}
          />
          {suffix ? (
            <Text
              x={block.x + PAD + Math.max(80, titleSize * 4)}
              y={block.y + h / 2 + titleSize * 0.4}
              width={block.width - PAD * 2}
              text={suffix}
              fontSize={bodySize}
              fontFamily={FONT}
              fill={tokens.textSecondary}
            />
          ) : null}
        </Group>
      );
    }

    case 'data.filter': {
      /*
       * Фильтр: условие сверху и подходящие записи под ним.
       *
       * Условие показано словами, а не полем ввода: в статическом
       * пакете отбора нет, и рисовать элемент управления значило бы
       * обещать функцию, которой не будет.
       */
      const field = prop(block, 'field', 'title');
      const operator = prop(block, 'operator', 'eq');
      const value = prop(block, 'value', '');
      const label = prop(block, 'label', '');
      const rows = recordLines(records);
      const top = block.y + PAD + (label ? titleSize + 8 : 0);

      return (
        <Group listening={false}>
          {label ? (
            <Text
              x={block.x + PAD}
              y={block.y + PAD}
              width={block.width - PAD * 2}
              text={label}
              fontSize={titleSize}
              fontStyle={headingWeight}
              fontFamily={FONT}
              fill={headingFill}
            />
          ) : null}
          <Rect
            x={block.x + PAD}
            y={top}
            width={block.width - PAD * 2}
            height={26}
            fill={tokens.panelSunken}
            cornerRadius={6}
          />
          <Text
            x={block.x + PAD + 10}
            y={top + 6}
            width={block.width - PAD * 2 - 20}
            text={`${field} ${operator} ${value}`.trim()}
            fontSize={bodySize}
            fontFamily={MONO}
            fill={tokens.textSecondary}
            ellipsis
          />
          {rows.length ? (
            <Text
              x={block.x + PAD}
              y={top + 36}
              width={block.width - PAD * 2}
              height={Math.max(18, h - PAD * 2 - titleSize - 50)}
              text={rows.slice(0, 3).join('\n')}
              fontSize={bodySize}
              fontFamily={FONT}
              fill={tokens.textPrimary}
              lineHeight={1.4}
            />
          ) : (
            <Text
              x={block.x + PAD}
              y={top + 36}
              width={block.width - PAD * 2}
              text="Источник не выбран"
              fontSize={bodySize}
              fontFamily={FONT}
              fill={tokens.textSecondary}
            />
          )}
        </Group>
      );
    }

    case 'data.sort': {
      /*
       * Сортировка: заголовок с направлением и порядок записей.
       * Направление показывается явно — по убыванию и по возрастанию
       * выглядят одинаково, если знать только столбик цифр.
       */
      const field = prop(block, 'field', 'title');
      const direction = prop(block, 'direction', 'asc');
      const limit = Number(block.props?.['limit'] ?? 10);
      const rows = recordLines(records);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={`${field} ${direction === 'desc' ? '↓' : '↑'}`}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          <Text
            x={block.x + PAD}
            y={block.y + PAD + titleSize + 8}
            width={block.width - PAD * 2}
            text={rows.length ? rows.slice(0, limit).join('\n') : 'Источник не выбран'}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textPrimary}
            lineHeight={1.4}
          />
        </Group>
      );
    }

    case 'data.related': {
      /*
       * Связанные записи: карточки с заголовком и подписью. Пока
       * связь не задана, видно пустой каркас — и это честно: молча
       * показать случайные записи значило бы выдать их за связанные.
       */
      const titleField = prop(block, 'titleField', '');
      const limit = Number(block.props?.['limit'] ?? 4);
      const rows = recordLines(records);
      const shown = rows.slice(0, limit);
      const cellW = (block.width - PAD * 2 - 12 * (shown.length - 1)) / Math.max(shown.length, 1);
      const top = block.y + PAD + titleSize + 10;
      const cellH = Math.max(30, h - PAD * 2 - titleSize - 10);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={titleField ? `По полю ${titleField}` : 'Связанные записи'}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {shown.length ? (
            shown.map((row, i) => (
              <Group key={`${block.id}-r${i}`}>
                <Rect
                  x={block.x + PAD + i * (cellW + 12)}
                  y={top}
                  width={cellW}
                  height={cellH}
                  fill={tokens.panel}
                  stroke={tokens.border}
                  strokeWidth={1}
                  cornerRadius={10}
                />
                <Text
                  x={block.x + PAD + i * (cellW + 12) + 12}
                  y={top + 12}
                  width={cellW - 24}
                  height={cellH - 24}
                  text={row}
                  fontSize={bodySize}
                  fontFamily={FONT}
                  fill={tokens.textPrimary}
                  wrap="word"
                  ellipsis
                />
              </Group>
            ))
          ) : (
            <Rect
              x={block.x + PAD}
              y={top}
              width={block.width - PAD * 2}
              height={cellH}
              fill={tokens.panelSunken}
              stroke={tokens.border}
              strokeWidth={1}
              strokeDash={[6, 4]}
              cornerRadius={10}
            />
          )}
        </Group>
      );
    }

    case 'data.form': {
      /*
       * Форма записи: поля из свойства fields и кнопка отправки.
       * Кнопка нарисована, но не работает: без рантайма отправлять
       * некуда, и подпись под формой об этом говорит прямо.
       */
      const heading = prop(block, 'heading', 'Форма');
      const submit = prop(block, 'submitLabel', 'Отправить');
      const fields = listProp(block, 'fields', 6, ['Имя', 'Телефон']);
      const top = block.y + PAD + titleSize + 10;
      const gap = 8;
      const fieldHeight = Math.max(24, (h - PAD * 2 - titleSize - 10 - 40 - gap * fields.length) / fields.length);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {fields.map((name, i) => (
            <Group key={`${block.id}-f${i}`}>
              <Text
                x={block.x + PAD}
                y={top + i * (fieldHeight + gap)}
                width={120}
                text={name}
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textSecondary}
                ellipsis
              />
              <Rect
                x={block.x + PAD + 124}
                y={top + i * (fieldHeight + gap) - 2}
                width={block.width - PAD * 2 - 124}
                height={fieldHeight}
                fill={tokens.panel}
                stroke={tokens.border}
                strokeWidth={1}
                cornerRadius={6}
              />
            </Group>
          ))}
          <Rect
            x={block.x + PAD}
            y={block.y + h - PAD - 30}
            width={Math.max(120, submit.length * 8 + 36)}
            height={30}
            fill={tokens.selectionBorder}
            cornerRadius={6}
          />
          <Text
            x={block.x + PAD}
            y={block.y + h - PAD - 21}
            width={Math.max(120, submit.length * 8 + 36)}
            align="center"
            text={submit}
            fontSize={bodySize}
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.canvas}
          />
        </Group>
      );
    }

    case 'media.audio': {
      /*
       * Аудио: панель плеера с названием. Кнопку воспроизведения
       * рисуем рамкой, а не сплошной заливкой: на холсте это макет,
       * и он должен читаться так же, как на странице.
       */
      const title = prop(block, 'title', 'Аудио');
      const src = prop(block, 'src', '');
      const top = block.y + PAD;
      const barH = 30;

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={top}
            width={block.width - PAD * 2}
            text={title}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
            ellipsis
          />
          <Rect
            x={block.x + PAD}
            y={top + titleSize + 10}
            width={block.width - PAD * 2}
            height={barH}
            fill={tokens.panel}
            stroke={tokens.border}
            strokeWidth={1}
            cornerRadius={8}
          />
          <Line
            points={[
              block.x + PAD + 14,
              top + titleSize + 25,
              block.x + PAD + 26,
              top + titleSize + 25,
            ]}
            stroke={tokens.selectionBorder}
            strokeWidth={3}
            lineCap="round"
          />
          <Line
            points={[
              block.x + PAD + 22,
              top + titleSize + 19,
              block.x + PAD + 22,
              top + titleSize + 31,
            ]}
            stroke={tokens.selectionBorder}
            strokeWidth={3}
            lineCap="round"
          />
          <Line
            points={[
              block.x + PAD + 42,
              top + titleSize + 25,
              block.x + PAD + 200,
              top + titleSize + 25,
            ]}
            stroke={tokens.border}
            strokeWidth={3}
            lineCap="round"
          />
          <Text
            x={block.x + PAD}
            y={top + titleSize + 48}
            width={block.width - PAD * 2}
            text={src ? 'Файл подключён' : 'Аудиофайл не подключён'}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
          />
        </Group>
      );
    }

    case 'text.code': {
      /*
       * Блок кода: тёмное полотно с моноширинным текстом и нумерацией
       * строк. Подсветка синтаксиса на холсте не нужна: она отвлекает
       * от оценки вёрстки, а на странице её делает браузер.
       */
      const heading = prop(block, 'heading', '');
      const code = prop(block, 'code', "console.log('Привет, мир!');");
      const language = prop(block, 'language', 'js');
      const top = block.y + PAD + (heading ? titleSize + 8 : 0);
      const areaH = Math.max(30, h - PAD * 2 - titleSize - (heading ? 8 : 0));
      const codeLines = textLines(code ?? '', 8);

      return (
        <Group listening={false}>
          {heading ? (
            <Text
              x={block.x + PAD}
              y={block.y + PAD}
              width={block.width - PAD * 2}
              text={heading}
              fontSize={titleSize}
              fontStyle={headingWeight}
              fontFamily={FONT}
              fill={headingFill}
            />
          ) : null}
          <Rect
            x={block.x + PAD}
            y={top}
            width={block.width - PAD * 2}
            height={areaH}
            fill={tokens.panelSunken}
            cornerRadius={8}
          />
          {codeLines.map((lineText, i) => (
            <Group key={`${block.id}-l${i}`}>
              <Text
                x={block.x + PAD + 10}
                y={top + 10 + i * (bodySize + 4)}
                width={20}
                text={String(i + 1)}
                fontSize={bodySize}
                fontFamily={MONO}
                fill={tokens.textSecondary}
              />
              <Text
                x={block.x + PAD + 34}
                y={top + 10 + i * (bodySize + 4)}
                width={block.width - PAD * 2 - 44}
                text={lineText}
                fontSize={bodySize}
                fontFamily={MONO}
                fill={tokens.textPrimary}
                ellipsis
              />
            </Group>
          ))}
          <Text
            x={block.x + block.width - PAD - 60}
            y={block.y + PAD}
            width={60}
            align="right"
            text={language}
            fontSize={bodySize}
            fontFamily={MONO}
            fill={tokens.textSecondary}
          />
        </Group>
      );
    }

    case 'social.links': {
      /*
       * Соцсети: адреса списком. Подписи нет — показывается сам
       * адрес, потому что без значка иконки ссылка должна оставаться
       * узнаваемой и в выгрузке.
       */
      const heading = prop(block, 'heading', 'Мы здесь');
      const links = listProp(block, 'links', 3, ['https://example.com/social']);
      const top = block.y + PAD + titleSize + 10;
      const rowH = Math.max(20, (h - PAD * 2 - titleSize - 10) / links.length);

      return (
        <Group listening={false}>
          <Text
            x={block.x + PAD}
            y={block.y + PAD}
            width={block.width - PAD * 2}
            text={heading}
            fontSize={titleSize}
            fontStyle={headingWeight}
            fontFamily={FONT}
            fill={headingFill}
          />
          {links.map((link, i) => (
            <Group key={`${block.id}-s${i}`}>
              <Line
                points={[
                  block.x + PAD + 4,
                  top + i * rowH + rowH / 2,
                  block.x + PAD + 12,
                  top + i * rowH + rowH / 2,
                ]}
                stroke={tokens.selectionBorder}
                strokeWidth={2}
                lineCap="round"
              />
              <Text
                x={block.x + PAD + 20}
                y={top + i * rowH + rowH / 2 - bodySize / 2}
                width={block.width - PAD * 2 - 20}
                text={link}
                fontSize={bodySize}
                fontFamily={MONO}
                fill={tokens.textPrimary}
                ellipsis
              />
            </Group>
          ))}
        </Group>
      );
    }

    case 'text.table': {
      /*
       * Таблица: сетка ячеек. Столбцы считаются по первой непустой
       * строке, а строки — по переводам строк, как их разбирает
       * выгрузка: разные разборы дали бы разные таблицы.
       */
      const heading = prop(block, 'heading', '');
      const rows = textLines(prop(block, 'rows', '') ?? '', 6);
      const tableRows: string[] = rows.length ? rows : [' '];
      const headerCount = Math.max(
        1,
        (tableRows[0] ?? '').split(';').filter((c) => c.trim()).length,
      );
      const top = block.y + PAD + (heading ? titleSize + 8 : 0);
      const areaH = Math.max(30, h - PAD * 2 - titleSize - (heading ? 8 : 0));
      const rowH = Math.max(16, areaH / tableRows.length);
      const colW = (block.width - PAD * 2) / headerCount;

      return (
        <Group listening={false}>
          {heading ? (
            <Text
              x={block.x + PAD}
              y={block.y + PAD}
              width={block.width - PAD * 2}
              text={heading}
              fontSize={titleSize}
              fontStyle={headingWeight}
              fontFamily={FONT}
              fill={headingFill}
            />
          ) : null}
          {tableRows.map((rowText, r) => (
            <Group key={`${block.id}-r${r}`}>
              <Rect
                x={block.x + PAD}
                y={top + r * rowH}
                width={block.width - PAD * 2}
                height={rowH}
                fill={r === 0 ? tokens.panelSunken : tokens.panel}
                stroke={tokens.border}
                strokeWidth={1}
              />
              {Array.from({ length: headerCount }, (_, c) => (
                <Text
                  key={`${block.id}-c${c}`}
                  x={block.x + PAD + c * colW + 8}
                  y={top + r * rowH + rowH / 2 - bodySize / 2}
                  width={colW - 16}
                  text={rowText.split(';')[c] ?? ''}
                  fontSize={bodySize}
                  fontStyle={r === 0 ? 'bold' : 'normal'}
                  fontFamily={FONT}
                  fill={r === 0 ? tokens.textPrimary : tokens.textSecondary}
                  ellipsis
                />
              ))}
            </Group>
          ))}
        </Group>
      );
    }

    case 'media.file': {
      /*
       * Файл: имя, рамка и подпись о размере. Без адреса рамка
       * показана пунктиром: файл ещё не прикреплён, и обещать
       * скачивание нечего.
       */
      const title = prop(block, 'title', 'Файл');
      const size = prop(block, 'size', '');
      const href = prop(block, 'href', '');
      const boxH = Math.min(52, h - PAD * 2);
      const top = block.y + h / 2 - boxH / 2;
      const boxW = Math.min(block.width - PAD * 2, 360);

      return (
        <Group listening={false}>
          <Rect
            x={block.x + PAD}
            y={top}
            width={boxW}
            height={boxH}
            fill={tokens.panel}
            stroke={tokens.border}
            strokeWidth={1}
            {...(href ? {} : { strokeDash: [6, 4] })}
            cornerRadius={8}
          />
          <Text
            x={block.x + PAD + 14}
            y={top + boxH / 2 - bodySize / 2 - (size ? 8 : 0)}
            width={boxW - 28}
            text={title}
            fontSize={bodySize}
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
            ellipsis
          />
          <Text
            x={block.x + PAD + 14}
            y={top + boxH / 2 + 4}
            width={boxW - 28}
            text={size || (href ? 'Файл для скачивания' : 'Файл не прикреплён')}
            fontSize={bodySize}
            fontFamily={FONT}
            fill={tokens.textSecondary}
            ellipsis
          />
        </Group>
      );
    }

    case 'nav.anchor': {
      /*
       * Якорь: метка в левом поле блока. Размер блока не важен —
       * он не виден на странице, поэтому на холсте показан пунктиром,
       * чтобы пустой блок не выглядел сломанным.
       */
      const label = prop(block, 'label', '');
      return (
        <Group listening={false}>
          <Rect
            x={block.x}
            y={block.y}
            width={block.width}
            height={block.height}
            stroke={tokens.selectionBorder}
            strokeWidth={1}
            strokeDash={[4, 4]}
            cornerRadius={4}
          />
          <Line
            points={[block.x + 12, block.y, block.x, block.y + 12]}
            stroke={tokens.selectionBorder}
            strokeWidth={1.5}
          />
          <Text
            x={block.x + 14}
            y={block.y + 6}
            width={block.width - 28}
            text={label || `#${prop(block, 'anchor', block.id)}`}
            fontSize={bodySize}
            fontFamily={MONO}
            fill={tokens.textSecondary}
            ellipsis
          />
        </Group>
      );
    }

    case 'shop.catalog': {
      /*
       * Каталог: сетка карточек. Каждая — рамка с местом под картинку,
       * названием и ценой. Именно такая структура повторяется в
       * выгрузке, поэтому на холсте видно то же, что увидит посетитель.
       */
      const rows = recordLines(records);
      const columns = Math.max(2, Math.min(4, Number(block.props?.['columns'] ?? 3)));
      const limit = Math.max(1, Number(block.props?.['limit'] ?? 12));
      const shown = rows.slice(0, limit);
      const top = block.y + PAD;
      const area = Math.max(40, h - PAD * 2);
      const cellW = (block.width - PAD * 2 - 12 * (columns - 1)) / columns;
      const rowsCount = Math.max(1, Math.ceil(shown.length / columns));
      const cellH = (area - 12 * (rowsCount - 1)) / rowsCount;

      return (
        <Group listening={false}>
          {shown.length
            ? shown.map((row, i) => {
                const col = i % columns;
                const line = Math.floor(i / columns);
                const x = block.x + PAD + col * (cellW + 12);
                const y = top + line * (cellH + 12);
                const parts = row.split(' \u00b7 ');
                const price = parts.length > 1 ? parts[parts.length - 1] : '';
                return (
                  <Group key={`${block.id}-p${i}`}>
                    <Rect
                      x={x}
                      y={y}
                      width={cellW}
                      height={cellH}
                      fill={tokens.panel}
                      stroke={tokens.border}
                      strokeWidth={1}
                      cornerRadius={10}
                    />
                    <Rect
                      x={x}
                      y={y}
                      width={cellW}
                      height={cellH * 0.45}
                      fill={tokens.panelSunken}
                      cornerRadius={[10, 10, 0, 0]}
                    />
                    <Text
                      x={x + 12}
                      y={y + cellH * 0.45 + 10}
                      width={cellW - 24}
                      text={parts[0] || 'Товар'}
                      fontSize={bodySize}
                      fontStyle="bold"
                      fontFamily={FONT}
                      fill={tokens.textPrimary}
                      ellipsis
                    />
                    {price ? (
                      <Text
                        x={x + 12}
                        y={y + cellH - 22}
                        width={cellW - 24}
                        text={price}
                        fontSize={bodySize}
                        fontFamily={MONO}
                        fill={tokens.selectionBorder}
                        ellipsis
                      />
                    ) : null}
                  </Group>
                );
              })
            : [
                <Text
                  key={`${block.id}-empty`}
                  x={block.x + PAD}
                  y={block.y + h / 2}
                  width={block.width - PAD * 2}
                  align="center"
                  text="Каталог пуст: источник не выбран или в нём нет записей"
                  fontSize={bodySize}
                  fontFamily={FONT}
                  fill={tokens.textSecondary}
                />,
              ]}
        </Group>
      );
    }

    case 'shop.card': {
      /*
       * Карточка товара: одно изображение, название, описание и цена.
       * Отличие от каталога видно сразу: блок высокий, в нём одно
       * изображение и подробное описание, а не сетка.
       */
      const rows = recordLines(records);
      const row = rows[0] ?? '';
      const parts = row.split(' \u00b7 ');
      const price = parts.length > 1 ? parts[parts.length - 1] : '';
      const button = prop(block, 'buttonLabel', 'Подробнее');
      const imageH = Math.max(40, h * 0.42);
      const top = block.y + PAD;

      return (
        <Group listening={false}>
          {row ? (
            <Group key={`${block.id}-card`}>
              <Rect
                x={block.x + PAD}
                y={top}
                width={block.width - PAD * 2}
                height={imageH}
                fill={tokens.panelSunken}
                stroke={tokens.border}
                strokeWidth={1}
                cornerRadius={10}
              />
              <Text
                x={block.x + block.width / 2 - 60}
                y={top + imageH / 2 - 10}
                width={120}
                align="center"
                text="Изображение"
                fontSize={bodySize}
                fontFamily={FONT}
                fill={tokens.textSecondary}
              />
              <Text
                x={block.x + PAD}
                y={top + imageH + 12}
                width={block.width - PAD * 2}
                text={parts[0] || 'Товар'}
                fontSize={titleSize}
                fontStyle="bold"
                fontFamily={FONT}
                fill={tokens.textPrimary}
                ellipsis
              />
              {price ? (
                <Text
                  x={block.x + PAD}
                  y={top + imageH + 16 + titleSize}
                  width={Math.max(120, block.width - PAD * 2 - 140)}
                  text={`${prop(block, 'pricePrefix', '')} ${price}`.trim()}
                  fontSize={Math.max(20, titleSize * 0.9)}
                  fontStyle="bold"
                  fontFamily={MONO}
                  fill={tokens.selectionBorder}
                  ellipsis
                />
              ) : null}
              <Rect
                x={block.x + block.width - PAD - 110}
                y={top + imageH + 16 + titleSize}
                width={110}
                height={30}
                fill={tokens.selectionBorder}
                cornerRadius={6}
              />
              <Text
                x={block.x + block.width - PAD - 110}
                y={top + imageH + 25 + titleSize}
                width={110}
                align="center"
                text={button}
                fontSize={bodySize}
                fontStyle="bold"
                fontFamily={FONT}
                fill={tokens.canvas}
                ellipsis
              />
            </Group>
          ) : (
            <Text
              x={block.x + PAD}
              y={block.y + h / 2}
              width={block.width - PAD * 2}
              align="center"
              text="Товар не выбран: источник не задан или пуст"
              fontSize={bodySize}
              fontFamily={FONT}
              fill={tokens.textSecondary}
            />
          )}
        </Group>
      );
    }

    case 'shop.price': {
      /*
       * Цена: крупная сумма с единицей измерения и префиксом «от».
       * Число моноширинным шрифтом — разряды не должны разъезжаться,
       * а в цене это видно сразу.
       */
      const rows = recordLines(records);
      const parts = (rows[0] ?? '').split(' \u00b7 ');
      const value = parts.length > 1 ? parts[parts.length - 1] : (parts[0] || '\u2014');
      const suffix = prop(block, 'suffix', '\u20bd');
      const prefix = prop(block, 'prefix', '');

      return (
        <Group listening={false}>
          {prefix ? (
            <Text
              x={block.x + PAD}
              y={block.y + h / 2 - titleSize * 0.5}
              width={80}
              text={prefix}
              fontSize={bodySize}
              fontFamily={FONT}
              fill={tokens.textSecondary}
            />
          ) : null}
          <Text
            x={block.x + PAD + (prefix ? 84 : 0)}
            y={block.y + h / 2 - titleSize * 0.7}
            width={block.width - PAD * 2 - (prefix ? 84 : 0)}
            text={`${value}${suffix ? ` ${suffix}` : ''}`.trim()}
            fontSize={Math.max(28, titleSize * 1.4)}
            fontStyle="bold"
            fontFamily={MONO}
            fill={tokens.textPrimary}
            ellipsis
          />
        </Group>
      );
    }

    default: {
      // Модуль без собственного представления: остаётся подпись с
      // идентификатором, чтобы блок был узнаваем на холсте.
      return (
        <Text
          key={`${block.id}-fallback`}
          x={block.x + PAD}
          y={block.y + 14}
          width={block.width - PAD * 2}
          text={`${block.label}\n${block.module}`}
          fontSize={12}
          fontFamily={FONT}
          fill={tokens.textSecondary}
          lineHeight={1.5}
          listening={false}
        />
      );
    }
  }
}
