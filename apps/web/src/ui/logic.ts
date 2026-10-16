/**
 * Клиент логики страницы (Logic Graph, ТЗ п.6.4).
 *
 * Граф хранится в документе проекта под ключом `logic`, а не в
 * отдельной сущности: логика описывает поведение той же страницы, и
 * версионировать её отдельно значило бы забыть, какая логика
 * соответствовала какой версии страницы.
 */

import { request } from './apiClient';

/** Роль ноды определяет её вид и то, куда от неё можно провести связь. */
export type NodeRole = 'trigger' | 'condition' | 'action';

export interface NodePropDef {
  name: string;
  type: string;
  required: boolean;
  default: unknown;
  options: string[];
  description: string;
}

export interface NodeTypeDef {
  id: string;
  title: string;
  role: NodeRole;
  roleLabel: string;
  where: 'browser' | 'runtime';
  description: string;
  props: NodePropDef[];
}

export interface LogicNode {
  id: string;
  type: string;
  props: Record<string, unknown>;
  x: number;
  y: number;
}

/** Связь. `branch` заполняется только у выходов условия. */
export interface LogicEdge {
  source: string;
  target: string;
  branch: '' | 'yes' | 'no';
}

export interface LogicGraph {
  nodes: LogicNode[];
  edges: LogicEdge[];
}

export interface LogicCheckResult {
  valid: boolean;
  problems: string[];
  stats?: { nodes: number; actions: number; requiresRuntime: boolean };
  script?: string;
}

export const logicApi = {
  types: () => request<{ types: NodeTypeDef[] }>('/logic/types/'),

  /** Граф проекта вместе с результатом проверки. */
  graph: (projectId: string) =>
    request<{
      projectId: string;
      graph: LogicGraph;
      empty: boolean;
      valid: boolean;
      problems: string[];
      stats?: { nodes: number; edges: number; triggers: number };
      types: NodeTypeDef[];
    }>(`/projects/${projectId}/logic/`),

  /** Проверка присланного графа и предпросмотр скомпилированного файла. */
  check: (projectId: string, graph: LogicGraph) =>
    request<LogicCheckResult>(`/projects/${projectId}/logic/check/`, {
      method: 'POST',
      body: JSON.stringify({ graph }),
    }),
};

/** Пустой граф: новый проект открывается без логики, а не с ошибкой. */
export const emptyGraph: LogicGraph = { nodes: [], edges: [] };

/** Тип ноды по идентификатору. */
export function typeOf(types: NodeTypeDef[], id: string): NodeTypeDef | undefined {
  return types.find((t) => t.id === id);
}
