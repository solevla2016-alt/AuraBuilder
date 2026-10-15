"""Компиляция логики в чистый JavaScript (ТЗ п.6.4).

Граф превращается в файл, который работает без редактора: ни модулей,
ни сборки, ни зависимостей. Это ровно то, что требует ТЗ — «экспорт
логики в чистый JavaScript» — и то, что позволяет отдать клиенту сайт,
работающий годами без платформы.

Каждая нода становится функцией. Так сделано не из любви к функциям:
условие с ветками «да» и «нет» внутри выражения теряло бы одну из них,
а вложенное условие — обе. Функции дают любую глубину и остаются
читаемыми: по сгенерированному файлу видно, что делает каждая нода.

Компиляция детерминированная: тот же граф даёт тот же файл. Иначе две
сборки одной версии различались бы побайтно, и сравнивать их было бы
невозможно. Порядок обхода зафиксирован: ноды по идентификатору.
"""

from __future__ import annotations

import json

from .graph import Graph, LogicError, Node, validate
from .nodes import ROLE_ACTION, ROLE_CONDITION

#: Версия формата. Пакет и рантайм сверяются по ней: старый рантайм с
#: новым файлом должен сказать об этом прямо, а не вести себя странно.
LOGIC_FORMAT = 1


#: Символы, опасные внутри <script>: разметка и разделители строк.
#: json их не экранирует, а вставка текста пользователя в файл без
#: этого закрывает тег и ломает страницу.
_UNSAFE = {
    '<': '\\u003c',
    '>': '\\u003e',
    '&': '\\u0026',
    '\u2028': '\\u2028',
    '\u2029': '\\u2029',
}


def _js_string(value: object) -> str:
    raw = value if isinstance(value, str) else str(value)
    for char, escape in _UNSAFE.items():
        raw = raw.replace(char, escape)
    return json.dumps(raw, ensure_ascii=False)


def _js_value(value: object) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return _js_string(value)


def _read_path(source: str) -> str:
    """Читает значение по пути вида data.cart.count."""
    parts = [part for part in str(source).split('.') if part]
    if not parts:
        raise LogicError(f'путь к значению пуст: {source!r}')
    expression = 'window'
    for part in parts:
        expression += (f'.{part}' if part.isidentifier()
                       else f'[{_js_string(part)}]')
    return expression


#: Сравнения условия. «Содержит» и пустые значения разбираются отдельно.
OPERATORS = {
    'eq': '===',
    'neq': '!==',
    'gt': '>',
    'gte': '>=',
    'lt': '<',
    'lte': '<=',
}


def condition_expression(node: Node) -> str:
    """Выражение условия ноды."""
    props = node.props
    if node.type == 'condition.always':
        return 'true'
    left = _read_path(props.get('source'))
    operator = str(props.get('operator') or 'eq')

    if operator == 'empty':
        return f'!{left}'
    if operator == 'notEmpty':
        return f'!!{left}'
    if operator == 'contains':
        # «Содержит» — вхождение подстроки; сравнение с отсутствующим
        # значением должно давать false, а не исключение.
        return (f'!!{left} && String({left}).indexOf('
                f'{_js_string(props.get("value"))}) !== -1')
    symbol = OPERATORS.get(operator)
    if symbol is None:
        raise LogicError(f'неизвестный оператор сравнения: {operator}')
    return f'{left} {symbol} {_js_value(props.get("value"))}'


def action_expression(node: Node) -> str:
    """Вызов действия ноды."""
    props = node.props
    kind = node.type
    if kind == 'action.showModule':
        return (f'__show({_js_string(props.get("blockId"))}, '
                f'{_js_string(props.get("animate") or "none")})')
    if kind == 'action.hideModule':
        return f'__hide({_js_string(props.get("blockId"))})'
    if kind == 'action.setData':
        return (f'__set({_read_path(props.get("source"))}, '
                f'{_js_value(props.get("value"))})')
    if kind == 'action.redirect':
        return f'location.href = {_js_string(props.get("url"))}'
    if kind == 'action.message':
        return (f'__message({_js_string(props.get("text"))}, '
                f'{_js_string(props.get("tone") or "info")})')
    if kind == 'action.emitSignal':
        # Данные передаются как есть, когда это путь к значению, и
        # как текст — когда человек написал литерал: различать
        # приходится на клиенте, потому что JSON.parse от «привет»
        # упал бы.
        payload = props.get('payload')
        return (f'__fire({_js_string(props.get("channel"))}, '
                f'window.__auraPayload ? window.__auraPayload('
                f'{_js_string(payload)}) : {_js_string(payload)})')
    if kind == 'action.submit':
        return (f'__submit({_js_string(props.get("blockId"))}, '
                f'{_js_string(props.get("endpoint") or "/api/forms")})')
    if kind == 'action.webhook':
        return (f'__bridge({_js_string(props.get("channel"))}, '
                f'{_js_string(props.get("bridge"))})')
    raise LogicError(f'неизвестный тип действия: {kind}')


#: Вспомогательные функции скомпилированной логики. Самодостаточны:
#: ни редактор, ни пакет им не нужны.
RUNTIME = """
var __signals = {};
function __onReady(fn) {
  if (document.readyState !== 'loading') fn();
  else document.addEventListener('DOMContentLoaded', fn);
}
function __set(target, value) { target = value; return target; }
function __block(id) {
  return document.querySelector('[data-block="' + id + '"]');
}
function __show(blockId, animate) {
  var el = __block(blockId);
  if (!el) return;
  el.hidden = false;
  if (animate && animate !== 'none') {
    el.style.transition = 'opacity .2s';
    el.style.opacity = '0';
    window.requestAnimationFrame(function () { el.style.opacity = '1'; });
  }
}
function __hide(blockId) {
  var el = __block(blockId);
  if (el) el.hidden = true;
}
function __message(text, tone) {
  var box = document.createElement('div');
  box.setAttribute('role', 'status');
  box.textContent = text;
  box.style.cssText = 'position:fixed;left:16px;right:16px;bottom:16px;'
    + 'padding:12px 16px;border-radius:10px;z-index:9999;color:#fff;'
    + 'font:15px/1.4 system-ui,-apple-system,sans-serif;background:'
    + (tone === 'error' ? '#b3261e' : tone === 'success' ? '#1e7d46' : '#333333');
  document.body.appendChild(box);
  window.setTimeout(function () { box.remove(); }, 4000);
}
function __submit(blockId, endpoint) {
  var holder = __block(blockId);
  var form = holder ? (holder.querySelector('form') || holder) : null;
  if (!form || !form.tagName) return;
  if (window.__auraSubmit) { window.__auraSubmit(form, endpoint); return; }
  var action = endpoint || form.getAttribute('action') || '/api/forms';
  var data = {};
  new FormData(form).forEach(function (value, key) { data[key] = value; });
  fetch(action, { method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(data) })
    .then(function () { __message('Заявка отправлена', 'success'); });
}
function __bridge(channel, target) {
  if (window.__auraBridge) window.__auraBridge(channel, target);
}
function __signal(channel, fn) { __signals[channel] = fn; }
function __fire(channel, payload) {
  var fn = __signals[channel];
  if (fn) fn(payload);
}
""".strip()


class _Emitter:
    """Собирает код по графу.

    Имена функций — по порядку нод в отсортированном списке, а не по
    идентификаторам: идентификатор может содержать что угодно, а
    имена функций попадают в файл как есть.
    """

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.names: dict[str, str] = {}
        for index, node in enumerate(sorted(graph.nodes, key=lambda n: n.id)):
            self.names[node.id] = f'__n{index}'

    def call(self, node: Node, indent: str) -> str:
        """Вызов ноды.

        Вызов функции, а не раскрытие тела: раскрытие продублировало
        бы ветки условия в обработчике и в самой функции, и файл
        распухал бы вдвое без изменения поведения.
        """
        return f'{indent}{self.names[node.id]}();'

    def branch(self, node: Node, branch: str) -> Node | None:
        for edge in self.graph.outgoing(node.id):
            if edge.branch == branch:
                target = self.graph.node(edge.target)
                if target is not None:
                    return target
        return None

    def node_body(self, node: Node, indent: str) -> str:
        kind = node.kind
        if kind is None:
            raise LogicError(f'неизвестный тип ноды: {node.type}')

        if kind.role == ROLE_ACTION:
            return f'{indent}{action_expression(node)}'

        if kind.role == ROLE_CONDITION:
            yes = self.branch(node, 'yes')
            no = self.branch(node, 'no')
            lines = [f'{indent}if ({condition_expression(node)}) {{']
            if yes is not None:
                # Ветка вызывает функцию, а не раскрывает тело: иначе
                # вложенное условие дублировалось бы здесь и в своей
                # функции, а та осталась бы мёртвым кодом.
                lines.append(self.call(yes, indent + '  '))
            else:
                lines.append(f'{indent}  /* нет ветки «да» */')
            lines.append(f'{indent}}}')
            if no is not None:
                lines.append(f'{indent}else {{')
                lines.append(self.call(no, indent + '  '))
                lines.append(f'{indent}}}')
            return '\n'.join(lines)

        # Активатор внутри цепочки — сигнальный мост.
        channel = node.props.get('channel') or node.id
        return f"{indent}__signal({_js_string(channel)}, function () {{}};"

    def trigger_body(self, node: Node, indent: str) -> str:
        """Код подписки активатора."""
        if node.type == 'trigger.click':
            selector = _js_string(f'[data-logic="{node.id}"]')
            event = _js_string(str(node.props.get('event') or 'click'))
            first = self._first_step(node)
            step = self.call(first, indent + '  ') if first else ''
            return (f'{indent}document.addEventListener({event}, '
                    'function (event) {'
                    f'{indent}  var el = event.target.closest({selector});'
                    f'{indent}  if (!el) return;'
                    f'\n{step}\n{indent}}});')
        if node.type == 'trigger.pageLoad':
            delay = node.props.get('delayMs') or 0
            first = self._first_step(node)
            step = self.call(first, indent + '    ') if first else ''
            return (f'{indent}__onReady(function () {{'
                    f'{indent}  window.setTimeout(function () {{'
                    f'\n{step}\n{indent}  }}, {_js_value(delay)});'
                    f'{indent}}});')
        if node.type == 'trigger.signal':
            channel = _js_string(str(node.props.get('channel') or node.id))
            first = self._first_step(node)
            step = self.call(first, indent + '  ') if first else ''
            return (f'{indent}__signal({channel}, function () {{'
                    f'\n{step}\n{indent}}});')
        raise LogicError(f'неизвестный тип активатора: {node.type}')

    def _first_step(self, node: Node) -> Node | None:
        edges = sorted(self.graph.outgoing(node.id),
                       key=lambda e: (e.branch != 'yes', e.target))
        for edge in edges:
            target = self.graph.node(edge.target)
            if target is not None:
                return target
        return None

    def script(self) -> str:
        nodes = sorted(self.graph.nodes, key=lambda n: n.id)
        chunks: list[str] = []
        for node in nodes:
            kind = node.kind
            if kind is None:
                continue
            if kind.role == ROLE_ACTION:
                chunks.append(f'function {self.names[node.id]}() {{\n'
                              f'{self.node_body(node, "  ")}\n}}')
            elif kind.role == ROLE_CONDITION:
                chunks.append(f'function {self.names[node.id]}() {{\n'
                              f'{self.node_body(node, "  ")}\n}}')
            # Активаторы получают подписку, а не тело: выполнять их
            # функцию напрямую незачем.
        triggers = sorted(self.graph.triggers(), key=lambda n: n.id)
        for node in triggers:
            chunks.append(self.trigger_body(node, ''))
        if not chunks:
            return ''
        return '\n\n'.join(chunks)


def compile_graph(raw: object) -> dict:
    """Компилирует граф. Возвращает скрипт и декларацию для рантайма."""
    graph = validate(raw)
    emitter = _Emitter(graph)
    body = emitter.script()

    header = (
        '/* Логика страницы AuraBuilder. Сгенерировано из графа нод:\n'
        f'   правьте граф в редакторе, а не этот файл. Формат '
        f'{LOGIC_FORMAT}. */'
    )
    if body:
        script = f'{header}\n(function () {{\n{RUNTIME}\n\n{body}\n}})();\n'
    else:
        script = f'{header}\n/* Граф пуст: выполнять нечего. */\n'

    declaration = {
        'format': LOGIC_FORMAT,
        'nodes': [
            {
                'id': node.id,
                'type': node.type,
                'role': node.kind.role if node.kind else None,
                'where': node.kind.where if node.kind else 'browser',
                'props': node.props,
            }
            for node in sorted(graph.nodes, key=lambda n: n.id)
        ],
        'edges': [
            {'source': e.source, 'target': e.target, 'branch': e.branch}
            for e in graph.edges
        ],
        'triggers': [node.id for node in sorted(graph.triggers(),
                                                key=lambda n: n.id)],
    }
    return {
        'script': script,
        'declaration': declaration,
        'nodes': len(graph.nodes),
        'actions': len(graph.actions()),
        'hasRuntimeNodes': any(
            node.kind is not None and node.kind.where == 'runtime'
            for node in graph.nodes
        ),
    }


__all__ = ['LOGIC_FORMAT', 'OPERATORS', 'RUNTIME', 'action_expression',
           'compile_graph', 'condition_expression']