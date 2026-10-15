"""Типы нод Logic Graph (ТЗ п.6.4, режим Logic Graph п.4.2).

Логика на сайте — это граф: событие («При клике») проходит через
условия («Если корзина не пуста») к действиям («Отправить заказ»).
Смысл описания типов в одном месте: редактор рисует библиотеку из
этого списка, компилятор проверяет по нему параметры, а пакет
экспортирует их же. Три разных места со своим списком типов разъедутся
при первом же добавлении ноды.

Собственная терминология ТЗ: Triggers — «Активаторы», Webhooks —
«Сигнальные мосты», Collections — «Узлы данных».

Ноды делятся на три роли, и роль важнее конкретного типа:

* **активатор** — вход графа, у него не должно быть входящих связей;
* **условие** — имеет два выхода: «да» и «нет»;
* **действие** — конечный узел, у него нет исходящих связей.

Роль проверяется компилятором: нода-действие с исходящей связью или
активатор со входящей — это ошибка сборки, а не «сработает как-нибудь».
"""

from __future__ import annotations

from dataclasses import dataclass, field

ROLE_TRIGGER = 'trigger'
ROLE_CONDITION = 'condition'
ROLE_ACTION = 'action'

ROLES = frozenset({ROLE_TRIGGER, ROLE_CONDITION, ROLE_ACTION})

#: Собственная терминология ролей в интерфейсе (ТЗ п.3.3).
ROLE_LABELS = {
    ROLE_TRIGGER: 'Активатор',
    ROLE_CONDITION: 'Условие',
    ROLE_ACTION: 'Действие',
}


@dataclass(frozen=True)
class NodeProp:
    """Одно настраиваемое свойство ноды."""

    name: str
    type: str
    required: bool = False
    default: object | None = None
    options: tuple[str, ...] = ()
    description: str = ''


@dataclass(frozen=True)
class NodeType:
    """Тип ноды графа."""

    id: str
    title: str
    role: str
    props: tuple[NodeProp, ...] = ()
    description: str = ''
    #: Исполняется ли нода в браузере посетителя или в рантайме.
    #: От этого зависит, попадёт ли она в пакет и в logic.json.
    where: str = 'browser'

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.props if p.default is not None}

    def required_props(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.props if p.required)


NODE_TYPES: dict[str, NodeType] = {}


def _add(node: NodeType) -> NodeType:
    if node.role not in ROLES:
        raise ValueError(f'неизвестная роль ноды: {node.role}')
    NODE_TYPES[node.id] = node
    return node


# --- Активаторы ------------------------------------------------------------

_add(NodeType(
    id='trigger.click',
    title='При клике',
    role=ROLE_TRIGGER,
    description='Срабатывает, когда посетитель нажал кнопку или ссылку',
    props=(
        NodeProp('blockId', 'text', True,
                 description='Блок, на котором слушается нажатие'),
        NodeProp('event', 'select', False, 'click',
                 options=('click', 'submit', 'change'),
                 description='Какое событие запускает цепочку'),
    ),
))

_add(NodeType(
    id='trigger.pageLoad',
    title='При загрузке страницы',
    role=ROLE_TRIGGER,
    description='Срабатывает один раз, когда страница открыта',
    props=(
        NodeProp('delayMs', 'number', False, 0,
                 description='Задержка в миллисекундах'),
    ),
))

_add(NodeType(
    id='trigger.signal',
    title='Сигнальный мост',
    role=ROLE_TRIGGER,
    description='Запускает цепочку по сигналу другой части логики '
                '(ТЗ: Webhooks — сигнальные мосты)',
    props=(
        NodeProp('channel', 'text', True,
                 description='Имя канала, на который отправляется сигнал'),
    ),
))

# --- Условия ---------------------------------------------------------------

_add(NodeType(
    id='condition.property',
    title='Если условие',
    role=ROLE_CONDITION,
    description='Сравнивает значение поля данных с заданным',
    props=(
        NodeProp('source', 'text', True,
                 description='Путь к значению: data.cart.count'),
        NodeProp('operator', 'select', False, 'eq',
                 options=('eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'contains',
                          'empty', 'notEmpty'),
                 description='Сравнение'),
        NodeProp('value', 'text', False, None,
                 description='С чем сравниваем; для empty не нужно'),
    ),
))

_add(NodeType(
    id='condition.always',
    title='Безусловный переход',
    role=ROLE_CONDITION,
    description='Всегда идёт по ветке «да»',
))

# --- Действия --------------------------------------------------------------

_add(NodeType(
    id='action.showModule',
    title='Показать модуль',
    role=ROLE_ACTION,
    description='Показывает ранее скрытый блок страницы',
    props=(
        NodeProp('blockId', 'text', True, description='Блок'),
        NodeProp('animate', 'select', False, 'fade',
                 options=('none', 'fade', 'slide'),
                 description='Появление'),
    ),
))

_add(NodeType(
    id='action.hideModule',
    title='Скрыть модуль',
    role=ROLE_ACTION,
    props=(NodeProp('blockId', 'text', True, description='Блок'),),
))

_add(NodeType(
    id='action.setData',
    title='Записать в узел данных',
    role=ROLE_ACTION,
    description='Меняет значение в узле данных (ТЗ: Collections)',
    props=(
        NodeProp('source', 'text', True, description='Путь: data.cart.count'),
        NodeProp('value', 'text', True, description='Значение'),
    ),
))

_add(NodeType(
    id='action.redirect',
    title='Перейти на адрес',
    role=ROLE_ACTION,
    props=(NodeProp('url', 'text', True, description='Адрес'),),
))

_add(NodeType(
    id='action.message',
    title='Показать сообщение',
    role=ROLE_ACTION,
    props=(
        NodeProp('text', 'text', True, description='Текст сообщения'),
        NodeProp('tone', 'select', False, 'info',
                 options=('info', 'success', 'error'),
                 description='Вид сообщения'),
    ),
))

_add(NodeType(
    id='action.emitSignal',
    title='Отправить сигнал',
    role=ROLE_ACTION,
    description='Запускает другую цепочку через сигнальный мост '
                '(ТЗ: Webhooks — сигнальные мосты)',
    props=(
        NodeProp('channel', 'text', True,
                 description='Канал, который слушает другой активатор'),
        NodeProp('payload', 'text', False, '',
                 description='Что передать: путь к значению или текст'),
    ),
))

_add(NodeType(
    id='action.submit',
    title='Отправить форму',
    role=ROLE_ACTION,
    description='Отправляет данные формы в рантайм',
    where='runtime',
    props=(
        NodeProp('blockId', 'text', True, description='Форма'),
        NodeProp('endpoint', 'text', False, '',
                 description='Путь на рантайме; пусто — /api/forms'),
    ),
))

_add(NodeType(
    id='action.webhook',
    title='Отправить в CRM',
    role=ROLE_ACTION,
    description='Передаёт данные в интеграцию (ТЗ: сигнальный мост)',
    where='runtime',
    props=(
        NodeProp('bridge', 'text', True,
                 description='Имя интеграции или адрес вебхука'),
        NodeProp('channel', 'text', True,
                 description='Канал данных для передачи'),
    ),
))


def node_type(node_id: str) -> NodeType | None:
    return NODE_TYPES.get(node_id)


def types_for_role(role: str) -> tuple[NodeType, ...]:
    return tuple(t for t in NODE_TYPES.values() if t.role == role)


def library() -> list[dict]:
    """Библиотека нод для левой панели редактора."""
    return [
        {
            'id': t.id,
            'title': t.title,
            'role': t.role,
            'roleLabel': ROLE_LABELS[t.role],
            'where': t.where,
            'description': t.description,
            'props': [
                {
                    'name': p.name,
                    'type': p.type,
                    'required': p.required,
                    'default': p.default,
                    'options': list(p.options),
                    'description': p.description,
                }
                for p in t.props
            ],
        }
        for t in NODE_TYPES.values()
    ]


__all__ = [
    'NODE_TYPES',
    'ROLE_ACTION',
    'ROLE_CONDITION',
    'ROLE_LABELS',
    'ROLE_TRIGGER',
    'ROLES',
    'NodeProp',
    'NodeType',
    'library',
    'node_type',
    'types_for_role',
]