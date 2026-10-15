"""Logic Graph: типы нод, проверка графа и компиляция (ТЗ п.6.4).

Проверяется не «скомпилировалось ли», а три свойства, на которых держится
доверие к сгенерированному файлу: он детерминирован, ветки условия не
теряются на любой глубине, а неверный граф останавливает сборку, а не
ломает сайт у посетителя.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from logic.compiler import LOGIC_FORMAT, compile_graph
from logic.graph import LogicError, extract, parse, validate
from logic.nodes import ROLE_ACTION, ROLE_CONDITION, ROLE_TRIGGER, library


def graph_of(nodes, edges) -> dict:
    return {'nodes': nodes, 'edges': edges}


def node(node_id: str, node_type: str, **props) -> dict:
    return {'id': node_id, 'type': node_type, 'props': props, 'x': 0, 'y': 0}


def edge(source: str, target: str, branch: str = '') -> dict:
    return {'source': source, 'target': target, 'branch': branch}


#: Граф из ТЗ: клик → условие → два разных действия.
CLICK_GRAPH = graph_of(
    [
        node('n1', 'trigger.click', blockId='b1'),
        node('n2', 'condition.property', source='data.cart.count',
             operator='gt', value='0'),
        node('n3', 'action.submit', blockId='b2'),
        node('n4', 'action.message', text='Корзина пуста', tone='info'),
    ],
    [
        edge('n1', 'n2'),
        edge('n2', 'n3', 'yes'),
        edge('n2', 'n4', 'no'),
    ],
)


class NodeLibraryTests(SimpleTestCase):
    def test_every_type_has_a_known_role(self):
        for item in library():
            self.assertIn(item['role'], ('trigger', 'condition', 'action'))

    def test_examples_from_the_spec_exist(self):
        ids = {item['id'] for item in library()}
        # Примеры ТЗ: «При клике», «Если условие», «Показать модуль»,
        # «Отправить в CRM».
        self.assertIn('trigger.click', ids)
        self.assertIn('condition.property', ids)
        self.assertIn('action.showModule', ids)
        self.assertIn('action.webhook', ids)

    def test_own_terminology_is_used(self):
        labels = {item['roleLabel'] for item in library()}
        self.assertEqual(labels, {'Активатор', 'Условие', 'Действие'})

    def test_server_nodes_are_marked(self):
        by_id = {item['id']: item for item in library()}
        self.assertEqual(by_id['action.submit']['where'], 'runtime')
        self.assertEqual(by_id['action.message']['where'], 'browser')


class GraphParsingTests(SimpleTestCase):
    def test_empty_graph_is_allowed(self):
        graph = validate({'nodes': [], 'edges': []})
        self.assertEqual(graph.nodes, ())

    def test_missing_graph_is_allowed(self):
        self.assertEqual(parse(None).nodes, ())

    def test_extract_picks_logic_from_document(self):
        self.assertEqual(extract({'logic': CLICK_GRAPH}), CLICK_GRAPH)
        self.assertIsNone(extract({'width': 1200}))

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(LogicError):
            validate(graph_of([node('a', 'action.message', text='x'),
                               node('a', 'action.message', text='y')], []))

    def test_unknown_type_is_refused(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of([node('a', 'action.выдумать')], []))
        self.assertIn('неизвестный тип', str(ctx.exception))

    def test_missing_required_prop_is_refused(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of([node('a', 'action.message')], []))
        self.assertIn('не заполнено', str(ctx.exception))

    def test_value_outside_options_is_refused(self):
        with self.assertRaises(LogicError):
            validate(graph_of(
                [node('a', 'condition.property', source='x', operator='магия')],
                [],
            ))

    def test_all_problems_are_reported_together(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of(
                [node('a', 'action.message'), node('b', 'action.нет')],
                [edge('a', 'missing')],
            ))
        message = str(ctx.exception)
        self.assertIn('не заполнено', message)
        self.assertIn('неизвестный тип', message)
        self.assertIn('missing', message)


class GraphStructureTests(SimpleTestCase):
    def test_action_cannot_have_outgoing_edge(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of(
                [node('a', 'trigger.click', blockId='b'),
                 node('b1', 'action.message', text='x'),
                 node('b2', 'action.hideModule', blockId='c')],
                [edge('a', 'b1'), edge('b1', 'b2')],
            ))
        self.assertIn('нет продолжения', str(ctx.exception))

    def test_trigger_cannot_have_incoming_edge(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of(
                [node('a', 'trigger.click', blockId='b'),
                 node('t2', 'trigger.pageLoad'),
                 node('c', 'action.message', text='x')],
                [edge('t2', 'a'), edge('a', 'c')],
            ))
        self.assertIn('нельзя вести связь', str(ctx.exception))

    def test_condition_edge_needs_branch(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of(
                [node('a', 'trigger.click', blockId='b'),
                 node('c', 'condition.always'),
                 node('d', 'action.message', text='x')],
                [edge('a', 'c'), edge('c', 'd')],
            ))
        self.assertIn('«да» или «нет»', str(ctx.exception))

    def test_two_edges_from_same_branch_are_refused(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of(
                [node('a', 'trigger.click', blockId='b'),
                 node('c', 'condition.always'),
                 node('d', 'action.message', text='x'),
                 node('e', 'action.message', text='y')],
                [edge('a', 'c'), edge('c', 'd', 'yes'), edge('c', 'e', 'yes')],
            ))
        self.assertIn('уже есть связь', str(ctx.exception))

    def test_self_loop_is_refused(self):
        with self.assertRaises(LogicError):
            validate(graph_of(
                [node('a', 'trigger.click', blockId='b')],
                [edge('a', 'a')],
            ))

    def test_cycle_is_detected(self):
        with self.assertRaises(LogicError) as ctx:
            validate(graph_of(
                [node('a', 'trigger.pageLoad'),
                 node('b', 'condition.always'),
                 node('c', 'condition.always'),
                 node('d', 'action.message', text='x')],
                [edge('a', 'b'), edge('b', 'c', 'yes'),
                 edge('c', 'b', 'yes'), edge('c', 'd', 'no')],
            ))
        self.assertIn('цикл', str(ctx.exception))

    def test_merging_branches_are_not_a_cycle(self):
        # Оба условия ведут в одно действие: это обычный «и/или»,
        # а не цикл, и запрещать его было бы неверно.
        graph = validate(graph_of(
            [node('a', 'trigger.pageLoad'),
             node('b', 'condition.always'),
             node('c', 'condition.always'),
             node('d', 'action.message', text='x')],
            [edge('a', 'b'), edge('b', 'c', 'yes'), edge('b', 'd', 'no'),
             edge('c', 'd', 'yes')],
        ))
        self.assertEqual(len(graph.nodes), 4)


class CompilerTests(SimpleTestCase):
    def test_script_contains_both_branches(self):
        result = compile_graph(CLICK_GRAPH)
        script = result['script']
        self.assertIn('if (', script)
        self.assertIn('else', script)
        self.assertIn('Корзина пуста', script)
        self.assertIn('__submit', script)

    def test_script_is_self_contained(self):
        script = compile_graph(CLICK_GRAPH)['script']
        # Ни редактора, ни внешней библиотеки: сайт должен работать
        # годами без платформы.
        for forbidden in ('import ', 'require(', 'https://cdn', 'fetch(\'http'):
            self.assertNotIn(forbidden, script)
        self.assertIn('document.addEventListener', script)

    def test_declaration_describes_graph(self):
        declaration = compile_graph(CLICK_GRAPH)['declaration']
        self.assertEqual(declaration['format'], LOGIC_FORMAT)
        self.assertEqual(declaration['triggers'], ['n1'])
        roles = {n['id']: n['role'] for n in declaration['nodes']}
        self.assertEqual(roles['n1'], ROLE_TRIGGER)
        self.assertEqual(roles['n2'], ROLE_CONDITION)
        self.assertEqual(roles['n3'], ROLE_ACTION)
        server = [n for n in declaration['nodes'] if n['where'] == 'runtime']
        self.assertEqual([n['id'] for n in server], ['n3'])

    def test_runtime_nodes_are_reported(self):
        self.assertTrue(compile_graph(CLICK_GRAPH)['hasRuntimeNodes'])
        simple = graph_of([node('a', 'trigger.pageLoad'),
                           node('b', 'action.message', text='x')],
                          [edge('a', 'b')])
        self.assertFalse(compile_graph(simple)['hasRuntimeNodes'])

    def test_empty_graph_compiles_to_no_op(self):
        result = compile_graph({'nodes': [], 'edges': []})
        self.assertEqual(result['nodes'], 0)
        self.assertIn('Граф пуст', result['script'])

    def test_compilation_is_deterministic(self):
        first = compile_graph(CLICK_GRAPH)
        second = compile_graph(json.loads(json.dumps(CLICK_GRAPH)))
        self.assertEqual(first['script'], second['script'])

    def test_node_order_does_not_change_result(self):
        # Порядок нод в документе не должен влиять на файл: иначе
        # перестановка нод в редакторе меняла бы сборку целиком.
        reordered = graph_of(list(reversed(CLICK_GRAPH['nodes'])),
                             CLICK_GRAPH['edges'])
        self.assertEqual(compile_graph(CLICK_GRAPH)['script'],
                         compile_graph(reordered)['script'])

    def test_values_are_escaped(self):
        graph = graph_of(
            [node('a', 'trigger.pageLoad'),
             node('b', 'action.message', text='</script><script>x')],
            [edge('a', 'b')],
        )
        script = compile_graph(graph)['script']
        self.assertNotIn('</script>', script)
        self.assertIn('\\u003c', script)

    def test_condition_with_only_yes_branch(self):  # noqa: D401
        graph = graph_of(
            [node('a', 'trigger.pageLoad'),
             node('b', 'condition.always'),
             node('c', 'action.message', text='да')],
            [edge('a', 'b'), edge('b', 'c', 'yes')],
        )
        script = compile_graph(graph)['script']
        # «else {» встречается только в сгенерированной части: в
        # вспомогательных функциях его нет, а «else if» в графе
        # невозможен — у условия ровно две ветки.
        self.assertNotIn('else {', script)
        self.assertIn('__message', script)

    def test_deep_nesting_keeps_all_branches(self):
        # Вложенное условие — проверка на то, что компилятор не
        # склеивает ветки в выражение и не теряет «нет».
        graph = graph_of(
            [node('a', 'trigger.pageLoad'),
             node('b1', 'condition.property', source='data.a', operator='eq',
                  value='1'),
             node('b2', 'condition.property', source='data.b', operator='eq',
                  value='2'),
             node('c1', 'action.message', text='оба'),
             node('c2', 'action.message', text='только первое'),
             node('c3', 'action.message', text='ничего')],
            [edge('a', 'b1'),
             edge('b1', 'b2', 'yes'), edge('b1', 'c2', 'no'),
             edge('b2', 'c1', 'yes'), edge('b2', 'c3', 'no')],
        )
        script = compile_graph(graph)['script']
        self.assertIn('оба', script)
        self.assertIn('только первое', script)
        self.assertIn('ничего', script)
        self.assertEqual(script.count('else {'), 2)

    def test_signal_bridge_starts_its_own_chain(self):
        # Сигнальный мост — вход графа: связать его с другой нодой
        # нельзя, в цепочку он не включается. Связываются две цепочки:
        # одна отправляет сигнал, вторая его слушает.
        graph = graph_of(
            [node('a', 'trigger.click', blockId='b1'),
             node('emit', 'action.emitSignal', channel='cart',
                  payload='data.cart.count'),
             node('listen', 'trigger.signal', channel='cart'),
             node('c', 'action.message', text='получено')],
            [edge('a', 'emit'), edge('listen', 'c')],
        )
        script = compile_graph(graph)['script']
        self.assertIn('__fire("cart"', script)
        self.assertIn('__signal("cart"', script)

    def test_reachability_warning_is_not_an_error(self):
        graph = graph_of(
            [node('a', 'trigger.pageLoad'),
             node('b', 'action.message', text='да'),
             node('orphan', 'action.message', text='сирота')],
            [edge('a', 'b')],
        )
        with self.assertLogs('logic.graph', level='WARNING') as caught:
            validate(graph)
        self.assertIn('orphan', '\n'.join(caught.output))