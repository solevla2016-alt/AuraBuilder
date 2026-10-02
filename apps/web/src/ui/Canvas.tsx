/**
 * Холст редактора на Konva.
 *
 * Вынесен отдельным модулем и подключается лениво: Konva весит около
 * 100 КБ gzip, и в критическом пути первого экрана он съедал запас
 * бюджета LCP (ТЗ п.1.3 — 1500 мс).
 *
 * Пока модуль не загружен, вместо холста показывается заглушка.
 * Экран редактора при этом уже отрисован: верхняя панель и палитра
 * не зависят от Konva.
 */

import { useEffect, useRef, useState } from 'react';
import { Layer, Rect, Stage, Text, Transformer } from 'react-konva';
import type Konva from 'konva';
import type { Block } from './project';

export interface CanvasProps {
  blocks: Block[];
  selectedId: string | null;
  tool: string;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
}

const PAGE_WIDTH = 720;
const PAGE_HEIGHT = 900;

const FILL_BY_KIND: Record<Block['kind'], string> = {
  section: 'var(--accentSurfaceSubtle)',
  text: 'var(--panel)',
  media: 'var(--panelSunken)',
};

export default function Canvas({ blocks, selectedId, tool, onSelect, onMove }: CanvasProps) {
  const stageRef = useRef<Konva.Stage>(null);
  const trRef = useRef<Konva.Transformer>(null);
  const [ready, setReady] = useState(false);

  // Первый кадр рисуем после появления узла Stage: до этого ref пуст,
  // и Transformer не находит выделение.
  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    if (!ready) return;
    const tr = trRef.current;
    const stage = stageRef.current;
    if (!tr || !stage) return;
    const node = selectedId ? stage.findOne(`#${selectedId}`) : null;
    tr.nodes(node ? [node] : []);
    tr.getLayer()?.batchDraw();
  }, [selectedId, ready, blocks]);

  const clearSelection = (e: Konva.KonvaEventObject<Event>) => {
    if (e.target === e.target.getStage()) onSelect(null);
  };

  return (
    <Stage
      ref={stageRef}
      width={PAGE_WIDTH}
      height={PAGE_HEIGHT}
      onClick={clearSelection}
      onTap={clearSelection}
    >
      <Layer>
        {/* Фон страницы пользователя — нейтральный, чтобы не тинтить дизайн */}
        <Rect
          x={0}
          y={0}
          width={PAGE_WIDTH}
          height={PAGE_HEIGHT}
          fill="var(--canvas)"
          cornerRadius={4}
          shadowColor="rgba(15,16,18,0.12)"
          shadowBlur={24}
          shadowOpacity={0.5}
          shadowOffsetY={4}
        />

        {blocks.map((b) => (
          <Rect
            key={b.id}
            id={b.id}
            x={b.x}
            y={b.y}
            width={b.width}
            height={b.height}
            fill={FILL_BY_KIND[b.kind]}
            stroke={selectedId === b.id ? 'var(--selectionBorder)' : 'var(--border)'}
            strokeWidth={selectedId === b.id ? 2 : 1}
            cornerRadius={8}
            draggable={tool === 'select'}
            onClick={() => onSelect(b.id === selectedId ? null : b.id)}
            onTap={() => onSelect(b.id === selectedId ? null : b.id)}
            onDragEnd={(e) => onMove(b.id, e.target.x(), e.target.y())}
          />
        ))}

        {blocks.map((b) => (
          <Text
            key={`${b.id}-label`}
            x={b.x + 14}
            y={b.y + 14}
            text={b.label}
            fontSize={13}
            fontFamily="Inter, sans-serif"
            fill="var(--textSecondary)"
            listening={false}
          />
        ))}

        {blocks.map((b) => (
          <Text
            key={`${b.id}-module`}
            x={b.x + 14}
            y={b.y + 36}
            text={b.module}
            fontSize={11}
            fontFamily="'JetBrains Mono', monospace"
            fill="var(--textDisabled)"
            listening={false}
          />
        ))}

        <Transformer
          ref={trRef}
          rotateEnabled={false}
          borderStroke="var(--selectionBorder)"
          anchorFill="var(--accentSurface)"
          anchorStroke="var(--selectionBorder)"
          anchorSize={10}
          anchorCornerRadius={2}
          padding={2}
          enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']}
          boundBoxFunc={(oldBox, newBox) =>
            newBox.width < 40 || newBox.height < 24 ? oldBox : newBox
          }
        />
      </Layer>
    </Stage>
  );
}
