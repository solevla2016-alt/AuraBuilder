"""Граф логики: структура, проверка и разбор.

Граф хранится в версии документа рядом с деревом страницы: логика
описывает поведение той же страницы, и версионировать её отдельно
значило бы забыть, какая версия логики соответствовала какой версии
страницы.

Проверка графа — до сборки. Пакет с логикой, которая падает на
полпути, хуже отказа: собранный сайт у посетителя ломается в тот
момент, когда он нажимает кнопку, и чинить это придётся вслепую.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .nodes import (
    ROLE_ACTION,
    ROLE_CONDITION,
    ROLE_TRIGGER,
    NodeType,
    node_type,
)

logger = logging.getLogger(__name__)

#: Ключ логики в документе проекта.
LOGIC_KEY = 'logic'


class LogicError(ValueError):
    """Граф логики неверен.

    Сообщение перечисляет все проблемы разом: заставлять пользователя
    находить их по одной после каждой неудачной сборки — плохой
    способ работы с графом.
    """


@dataclass(frozen=True)
class Node:
    """Нода графа."""

    id: str
    type: str
    props: dict
    x: float = 0
    y: float = 0

    @property
    def kind(self) -> NodeType | None:
        return node_type(self.type)


@dataclass(frozen=True)
class Edge:
    """Связь между нодами.

    Выход условия помечен: у него два выхода — «да» и «нет», и без
    пометки компилятор не знает, куда вести посетителя.
    """

    source: str
    target: str
    #: '', 'yes' или 'no' — выход условия; пусто у прочих ролей.
    branch: str = ''


@dataclass
class Graph:
    """Проверенный граф логики."""

    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    by_id: dict[str, Node] = field(default_factory=dict)

    def node(self, node_id: str) -> Node | None:
        return self.by_id.get(node_id)

    def outgoing(self, node_id: str) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges if e.source == node_id)

    def triggers(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.kind and n.kind.role == ROLE_TRIGGER)

    def actions(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.kind and n.kind.role == ROLE_ACTION)


def _as_str(value, default: str = '') -> str:
    return value if isinstance(value, str) else default


def parse(raw: object) -> Graph:
    """Разбирает граф из документа. Не проверяет — см. `validate`."""
    if raw is None:
        return Graph()
    if not isinstance(raw, dict):
        raise LogicError('логика должна быть объектом с нодами и связями')

    nodes: list[Node] = []
    seen: set[str] = set()
    for item in raw.get('nodes') or []:
        if not isinstance(item, dict):
            raise LogicError('нода описана не объектом')
        node_id = _as_str(item.get('id')).strip()
        if not node_id:
            raise LogicError('у ноды нет идентификатора')
        if node_id in seen:
            raise LogicError(f'идентификатор ноды повторяется: {node_id}')
        seen.add(node_id)
        props = item.get('props')
        nodes.append(Node(
            id=node_id,
            type=_as_str(item.get('type')),
            props=props if isinstance(props, dict) else {},
            x=_as_number(item.get('x')),
            y=_as_number(item.get('y')),
        ))

    edges: list[Edge] = []
    for item in raw.get('edges') or []:
        if not isinstance(item, dict):
            raise LogicError('связь описана не объектом')
        source = _as_str(item.get('source')).strip()
        target = _as_str(item.get('target')).strip()
        if not source or not target:
            raise LogicError('связь требует начало и конец')
        branch = _as_str(item.get('branch')).strip().lower()
        edges.append(Edge(source=source, target=target,
                          branch=branch if branch in ('yes', 'no') else ''))

    graph = Graph(nodes=tuple(nodes), edges=tuple(edges))
    graph.by_id = {n.id: n for n in nodes}
    return graph


def _as_number(value, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def validate(raw: object) -> Graph:
    """Проверяет граф и возвращает его в разобранном виде.

    Проверяется то, что ломает исполнение: неизвестные типы, связи в
    никуда, обязательные параметры, входящие связи у активаторов,
    исходящие у действий и циклы.

    Недостижимость — не ошибка, а предупреждение: ноду могли оставить
    на будущее, и запрещать собирать из-за этого нельзя. Но сказать
    об этом надо, иначе человек будет искать, почему его логика не
    сработала.
    """
    graph = parse(raw)
    problems: list[str] = []

    if not graph.nodes and not graph.edges:
        return graph

    for node in graph.nodes:
        kind = node.kind
        if kind is None:
            problems.append(f'неизвестный тип ноды: {node.type} ({node.id})')
            continue
        for prop in kind.required_props():
            if _as_str(node.props.get(prop)).strip() == '':
                problems.append(
                    f'у ноды «{kind.title}» не заполнено поле «{prop}» '
                    f'({node.id})',
                )
        # Свойства со списком значений проверяются по списку: опечатка
        # в значении сравнения тихо ломала бы условие.
        for prop in kind.props:
            if prop.options and prop.name in node.props:
                value = node.props[prop.name]
                if value not in prop.options:
                    problems.append(
                        f'у ноды «{kind.title}» поле «{prop.name}» '
                        f'должно быть одним из: {", ".join(prop.options)}',
                    )

    for edge in graph.edges:
        if edge.source not in graph.by_id:
            problems.append(f'связь начинается в несуществующей ноде: '
                            f'{edge.source}')
        if edge.target not in graph.by_id:
            problems.append(f'связь ведёт в несуществующую ноду: '
                            f'{edge.target}')
        if edge.source == edge.target:
            problems.append(f'нода соединена сама с собой: {edge.source}')
        source = graph.node(edge.source)
        target = graph.node(edge.target)
        if source is not None and source.kind is not None:
            if source.kind.role == ROLE_ACTION:
                problems.append(
                    f'из действия «{source.kind.title}» ({edge.source}) '
                    'нельзя провести связь: у действия нет продолжения',
                )
            if source.kind.role == ROLE_CONDITION and edge.branch == '':
                problems.append(
                    f'у условия «{source.kind.title}» ({edge.source}) '
                    'связь должна иметь ветку «да» или «нет»',
                )
        if target is not None and target.kind is not None:
            if target.kind.role == ROLE_TRIGGER:
                problems.append(
                    f'в активатор «{target.kind.title}» ({edge.target}) '
                    'нельзя вести связь: он начинает цепочку сам',
                )

    # Две связи из одного выхода условия перетирали бы друг друга:
    # посетитель ушёл бы по последней, а интерфейс показывал бы обе.
    seen_out: set[tuple[str, str]] = set()
    for edge in graph.edges:
        if edge.source not in graph.by_id:
            continue
        source = graph.node(edge.source)
        if source is None or source.kind is None:
            continue
        key = (edge.source, edge.branch) if source.kind.role == ROLE_CONDITION \
            else (edge.source, '')
        if key in seen_out:
            problems.append(
                f'из ноды «{source.kind.title}» ({edge.source}) уже есть '
                'связь с такой же веткой',
            )
        seen_out.add(key)

    problems.extend(_cycles(graph))

    if problems:
        raise LogicError('; '.join(problems))

    for warning in _unreachable(graph):
        logger.warning('%s', warning)
    return graph


def _cycles(graph: Graph) -> list[str]:
    """Ищет циклы: без обнаружения они исполнялись бы вечно."""
    found: list[str] = []
    colour: dict[str, int] = {}  # 0 — смотрим, 1 — в пути, 2 — готов

    def visit(node_id: str, path: list[str]) -> None:
        colour[node_id] = 1
        path.append(node_id)
        for edge in graph.outgoing(node_id):
            target = graph.node(edge.target)
            if target is None or target.kind is None:
                continue
            # Условие с обеими ветками ведёт в два места, и сходящиеся
            # ветки — обычное дело, а не цикл. Циклом считается
            # возвращение в ноду, которая сейчас в пути.
            if colour.get(edge.target) == 1:
                cycle = path[path.index(edge.target):] + [edge.target]
                if len(found) < 5:
                    found.append(' → '.join(cycle))
            elif colour.get(edge.target) is None:
                visit(edge.target, path)
        path.pop()
        colour[node_id] = 2

    for node in graph.nodes:
        if colour.get(node.id) is None:
            visit(node.id, [])
    return [f'в графе есть цикл: {cycle}' for cycle in found]


def _unreachable(graph: Graph) -> list[str]:
    """Ноды, до которых не дойти ни от одного активатора."""
    reachable: set[str] = set()
    stack = [n.id for n in graph.triggers()]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for edge in graph.outgoing(current):
            stack.append(edge.target)
    orphans = [n.id for n in graph.nodes if n.id not in reachable]
    if not orphans:
        return []
    return [
        'до этих нод нельзя дойти от активатора ('
        + ', '.join(orphans) + '): они не выполнятся',
    ]


def extract(document: dict) -> object:
    """Достаёт логику из документа проекта."""
    if not isinstance(document, dict):
        return None
    return document.get(LOGIC_KEY)


def attach(document: dict, graph: object) -> dict:
    """Кладёт логику в документ проекта."""
    if graph is not None:
        document[LOGIC_KEY] = graph
    return document


def is_empty(raw: object) -> bool:
    if not isinstance(raw, dict):
        return True
    return not raw.get('nodes') and not raw.get('edges')


__all__ = [
    'Edge',
    'Graph',
    'LOGIC_KEY',
    'LogicError',
    'Node',
    'attach',
    'extract',
    'is_empty',
    'parse',
    'validate',
]