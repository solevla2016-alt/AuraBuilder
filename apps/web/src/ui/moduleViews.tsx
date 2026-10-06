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
import { Group, Line, Rect, Text } from 'react-konva';
import type { Block } from './project';
import { cellText, type DataRecord } from './data';
import type { CanvasTokens } from './useCanvasTokens';

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
): ReactNode {
  const h = block.height;
  const titleSize = fontFor(h, 0.13, 14, 30);
  const bodySize = fontFor(h, 0.06, 11, 15);

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
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
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
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
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
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
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
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
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
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
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
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
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
            fontStyle="bold"
            fontFamily={FONT}
            fill={tokens.textPrimary}
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
            fontFamily={FONT}
            fill={tokens.textPrimary}
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