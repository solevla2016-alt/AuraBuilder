/**
 * Экран Logic Graph (ТЗ п.6.4, режим п.4.2).
 *
 * Сетка нод слева — библиотека, в центре — сам граф, справа — свойства
 * выбранной ноды. Три части, как в ТЗ: библиотека активаторов,
 * условий и действий слева, сетка с соединениями по центру, свойства
 * справа.
 *
 * Рисуем сами, без библиотеки для графов: нод немного, правил
 * соединения три, а лишняя зависимость весила бы больше всей
 * остальной логики экрана.
 *
 * Что экрану нельзя делать:
 *
 * 1. Сохранять непроверенный граф. Проверка идёт тем же кодом, что и
 *    сборка, и отказ показывается здесь, а не через час при
 *    публикации.
 * 2. Молчать об отзыве: сохранение идёт в документ проекта, поэтому
 *    редактор и экран логики должны видеть одно и то же дерево.
 * 3. Терять несохранённое: перед уходом с экрана изменения уже в
 *    документе, отдельной кнопки «применить» нет.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import { api } from './api';
import {
  emptyGraph,
  logicApi,
  typeOf,
  type LogicEdge,
  type LogicGraph,
  type LogicNode,
  type NodeRole,
  type NodeTypeDef,
} from './logic';
import type { PageTree } from './project';
import './logic.css';

type Props = {
  projectId: string;
  projectName: string;
  onBack: () => void;
};

/** Роли идут в порядке работы: событие → условие → действие. */
const ROLE_ORDER: NodeRole[] = ['trigger', 'condition', 'action'];

const NODE_WIDTH = 200;
const NODE_HEIGHT = 64;

/** Цвет роли: у активатора, условия и действия — разный. */
const ROLE_CLASS: Record<NodeRole, string> = {
  trigger: 'logic__node--trigger',
  condition: 'logic__node--condition',
  action: 'logic__node--action',
};

/**
 * Следующий свободный идентификатор ноды.
 *
 * Считается по уже добавленным нодам, а не по числу типов в
 * библиотеке: два добавления подряд дали бы один и тот же id, и две
 * ноды слиплись бы в одну — с потерей связи и ошибкой при сборке.
 */
function newId(nodes: LogicNode[]): string {
  let max = 0;
  for (const node of nodes) {
    const match = /^n(\d+)$/.exec(node.id);
    if (match) max = Math.max(max, Number(match[1]));
  }
  return `n${max + 1}`;
}

export function LogicScreen({ projectId, projectName, onBack }: Props) {
  const [types, setTypes] = useState<NodeTypeDef[]>([]);
  const [graph, setGraph] = useState<LogicGraph>(emptyGraph);
  const [selected, setSelected] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [script, setScript] = useState<string | null>(null);
  const [version, setVersion] = useState<number | undefined>(undefined);
  const [tree, setTree] = useState<PageTree | null>(null);
  /** Линия, которую пользователь тянет из выхода ноды. */
  const [linking, setLinking] = useState<{ from: string; branch: string; x: number; y: number } | null>(null);
  const surface = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    void logicApi
      .types()
      .then((body) => setTypes(body.types))
      .catch(() => setProblems(['Не удалось загрузить библиотеку нод.']));
  }, []);

  /*
   * Дерево запрашивается здесь, а не передаётся из редактора.
   *
   * Редактор держит своё состояние и сохраняет сам; переданный снимок
   * к моменту открытия логики был бы уже не тем, что лежит на
   * сервере, и сохранение записало бы поверх чужой правки. Источник
   * истины один — документ проекта.
   */
  useEffect(() => {
    let cancelled = false;
    void api
      .getProject(projectId)
      .then((project) => {
        if (cancelled) return;
        const stored = (project.tree as { logic?: LogicGraph }).logic;
        setTree(project.tree);
        setVersion(project.version);
        setGraph(stored && Array.isArray(stored.nodes) ? stored : emptyGraph);
      })
      .catch(() => {
        if (!cancelled) setProblems(['Не удалось загрузить проект.']);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const selectedNode = selected ? (graph.nodes.find((n) => n.id === selected) ?? null) : null;
  const selectedType = selectedNode ? typeOf(types, selectedNode.type) : undefined;

  const pointOf = useCallback(
    (node: LogicNode) => ({
      x: node.x + NODE_WIDTH / 2,
      y: node.y + NODE_HEIGHT / 2,
    }),
    [],
  );

  const addNode = useCallback(
    (def: NodeTypeDef) => {
      setGraph((prev) => {
        const id = newId(prev.nodes);
        const count = prev.nodes.length;
        const props: Record<string, unknown> = {};
        def.props.forEach((p) => {
          if (p.default !== null && p.default !== undefined) props[p.name] = p.default;
        });
        // Ноды раскладываются лесенкой: координаты по сетке читаются
        // глазом, а не вычисляются по числу уже добавленных.
        return {
          ...prev,
          nodes: [
            ...prev.nodes,
            {
              id,
              type: def.id,
              props,
              x: 60 + (count % 3) * 260,
              y: 60 + Math.floor(count / 3) * 140,
            },
          ],
        };
      });
      setScript(null);
    },
    [],
  );

  const moveNode = useCallback((id: string, x: number, y: number) => {
    setGraph((prev) => ({
      ...prev,
      nodes: prev.nodes.map((n) => (n.id === id ? { ...n, x: Math.max(0, x), y: Math.max(0, y) } : n)),
    }));
  }, []);

  const removeNode = useCallback((id: string) => {
    setGraph((prev) => ({
      nodes: prev.nodes.filter((n) => n.id !== id),
      // Связи удалённой ноды исчезают вместе с ней: оставить их
      // значило бы оставить граф, который невозможно отрисовать.
      edges: prev.edges.filter((e) => e.source !== id && e.target !== id),
    }));
    setSelected((current) => (current === id ? null : current));
    setScript(null);
  }, []);

  const removeEdge = useCallback((edge: LogicEdge) => {
    setGraph((prev) => ({
      ...prev,
      edges: prev.edges.filter(
        (e) => !(e.source === edge.source && e.target === edge.target && e.branch === edge.branch),
      ),
    }));
    setScript(null);
  }, []);

  const connect = useCallback(
    (from: string, branch: string, to: string) => {
      setGraph((prev) => {
        const target = prev.nodes.find((n) => n.id === to);
        const source = prev.nodes.find((n) => n.id === from);
        if (!target || !source) return prev;
        const next: LogicEdge = {
          source: from,
          target: to,
          branch: branch === 'yes' || branch === 'no' ? branch : '',
        };
        // Повторная связь из того же выхода заменяет прежнюю: две
        // связи из одной ветки означали бы «ушёл по последней».
        const without = prev.edges.filter(
          (e) => !(e.source === from && (branch ? e.branch === branch : true)),
        );
        return { ...prev, edges: [...without, next] };
      });
      setScript(null);
    },
    [],
  );

  const setProp = useCallback((nodeId: string, name: string, value: unknown) => {
    setGraph((prev) => ({
      ...prev,
      nodes: prev.nodes.map((n) => (n.id === nodeId ? { ...n, props: { ...n.props, [name]: value } } : n)),
    }));
    setScript(null);
  }, []);

  const save = useCallback(async () => {
    setBusy(true);
    setNotice(null);
    try {
      const check = await logicApi.check(projectId, graph);
      setProblems(check.problems ?? []);
      setScript(check.script ?? null);
      if (!check.valid) {
        setNotice('Граф не сохранён: исправьте ошибки, они перечислены ниже.');
        return;
      }
      if (!tree) throw new Error('Дерево проекта ещё загружается.');
      const nextTree = { ...tree, logic: graph } as PageTree;
      const saved = await api.saveProject(projectId, projectName, nextTree, version);
      setTree(saved.tree);
      setVersion(saved.version);
      setNotice('Логика сохранена в проекте и попадёт в следующую сборку.');
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : 'Не удалось сохранить логику.');
    } finally {
      setBusy(false);
    }
  }, [graph, projectId, projectName, tree, version]);

  /** Точка внутри поверхности — координаты относительно неё. */
  const localPoint = (event: { clientX: number; clientY: number }) => {
    const box = surface.current?.getBoundingClientRect();
    return {
      x: event.clientX - (box?.left ?? 0),
      y: event.clientY - (box?.top ?? 0),
    };
  };

  return (
    <main className="logic">
      <header className="logic__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Логика: {projectName}</h1>
        <button type="button" className="btn btn--primary" onClick={() => void save()} disabled={busy}>
          {busy ? 'Сохраняем…' : 'Сохранить логику'}
        </button>
      </header>

      {notice ? (
        <p className="vers__ok" role="status">
          {notice}
        </p>
      ) : null}

      <div className="logic__body">
        <aside className="logic__lib" aria-label="Библиотека нод">
          {ROLE_ORDER.map((role) => (
            <section key={role}>
              <h2 className="logic__role">{types.find((t) => t.role === role)?.roleLabel ?? role}</h2>
              {types
                .filter((t) => t.role === role)
                .map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`logic__lib-item ${ROLE_CLASS[t.role]}`}
                    title={t.description}
                    onClick={() => addNode(t)}
                  >
                    <span>{t.title}</span>
                    {t.where === 'runtime' ? <em>рантайм</em> : null}
                  </button>
                ))}
            </section>
          ))}
        </aside>

        <section
          className="logic__canvas"
          ref={surface}
          onPointerMove={(event) => {
            if (!linking) return;
            const p = localPoint(event);
            setLinking({ ...linking, x: p.x, y: p.y });
          }}
          onPointerUp={(event) => {
            if (!linking) return;
            const target = document
              .elementFromPoint(event.clientX, event.clientY)
              ?.closest('[data-node-id]');
            const to = target?.getAttribute('data-node-id') ?? null;
            setLinking(null);
            if (to && to !== linking.from) connect(linking.from, linking.branch, to);
          }}
        >
          <svg className="logic__wires" aria-hidden="true">
            {graph.edges.map((edge) => {
              const from = graph.nodes.find((n) => n.id === edge.source);
              const to = graph.nodes.find((n) => n.id === edge.target);
              if (!from || !to) return null;
              const a = pointOf(from);
              const b = pointOf(to);
              return (
                <g key={`${edge.source}-${edge.branch}-${edge.target}`}>
                  <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="logic__wire" />
                  <circle
                    cx={b.x}
                    cy={b.y}
                    r={6}
                    className="logic__wire-hit"
                    onClick={() => removeEdge(edge)}
                  >
                    <title>{`Убрать связь ${edge.source} → ${edge.target}`}</title>
                  </circle>
                </g>
              );
            })}
            {linking ? (
              <line
                x1={linking.x}
                y1={linking.y}
                x2={linking.x}
                y2={linking.y}
                className="logic__wire logic__wire--draft"
              />
            ) : null}
          </svg>

          {graph.nodes.length === 0 ? (
            <p className="logic__hint">
              Нажмите на ноду в библиотеке слева. Граф пуст — логика ничего не делает.
            </p>
          ) : null}

          {graph.nodes.map((node) => {
            const def = typeOf(types, node.type);
            const role: NodeRole = def?.role ?? 'action';
            return (
              <div
                key={node.id}
                data-node-id={node.id}
                className={`logic__node ${ROLE_CLASS[role]}`}
                style={{ left: node.x, top: node.y, width: NODE_WIDTH, height: NODE_HEIGHT }}
                onPointerDown={(event) => {
                  (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
                  const start = localPoint(event);
                  const origin = { x: node.x, y: node.y };
                  const move = (e: PointerEvent) => moveNode(node.id, origin.x + e.clientX - start.x, origin.y + e.clientY - start.y);
                  const up = () => {
                    window.removeEventListener('pointermove', move);
                    window.removeEventListener('pointerup', up);
                  };
                  window.addEventListener('pointermove', move);
                  window.addEventListener('pointerup', up);
                  setSelected(node.id);
                }}
              >
                <strong>{def?.title ?? node.type}</strong>
                {def ? <span className="logic__node-id">{node.id}</span> : null}
                {role === 'condition' ? (
                  <span className="logic__outs">
                    <button
                      type="button"
                      className="logic__out logic__out--yes"
                      onClick={(event) => {
                        const p = localPoint(event);
                        setLinking({ from: node.id, branch: 'yes', x: p.x, y: p.y });
                      }}
                    >
                      да
                    </button>
                    <button
                      type="button"
                      className="logic__out logic__out--no"
                      onClick={(event) => {
                        const p = localPoint(event);
                        setLinking({ from: node.id, branch: 'no', x: p.x, y: p.y });
                      }}
                    >
                      нет
                    </button>
                  </span>
                ) : role === 'action' ? null : (
                  <button
                    type="button"
                    className="logic__out"
                    onClick={(event) => {
                      const p = localPoint(event);
                      setLinking({ from: node.id, branch: '', x: p.x, y: p.y });
                    }}
                  >
                    выход
                  </button>
                )}
              </div>
            );
          })}
        </section>

        <aside className="logic__props" aria-label="Свойства ноды">
          {selectedNode && selectedType ? (
            <>
              <h2 className="logic__role">{selectedType.title}</h2>
              <p className="props__note">{selectedType.description}</p>
              {selectedType.props.map((prop) => (
                <label key={prop.name} className="prop__label">
                  {prop.name}
                  {prop.options.length ? (
                    <select
                      className="prop__input"
                      value={String(selectedNode.props[prop.name] ?? prop.default ?? prop.options[0])}
                      onChange={(e) => setProp(selectedNode.id, prop.name, e.target.value)}
                    >
                      {prop.options.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="prop__input"
                      value={String(selectedNode.props[prop.name] ?? '')}
                      onChange={(e) => setProp(selectedNode.id, prop.name, e.target.value)}
                    />
                  )}
                  {prop.required ? <span className="logic__required">обязательное</span> : null}
                </label>
              ))}
              <button type="button" className="btn" onClick={() => removeNode(selectedNode.id)}>
                Удалить ноду
              </button>
            </>
          ) : (
            <p className="props__note">Выберите ноду на сетке — здесь её свойства.</p>
          )}

          {problems.length ? (
            <ul className="logic__problems">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}

          {script ? (
            <details className="logic__script">
              <summary>Скомпилированный файл</summary>
              <pre>{script}</pre>
            </details>
          ) : null}
        </aside>
      </div>
    </main>
  );
}
