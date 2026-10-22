"""Сериализаторы проекта.

Валидация дерева повторяет клиентскую (apps/web/src/ui/project.ts), но
на сервере это обязательно: клиентскую проверку можно обойти, а в базу
не должно попасть ничего, что сломает экспорт (ТЗ п.16.2).
"""

import math
import re
from typing import Any

from rest_framework import serializers

from .models import Page, Project, default_tree
from .module_registry import MODULE_IDS, schema_for

MAX_BLOCKS = 500
MAX_LABEL = 200
MAX_CONTENT = 5000
MAX_PROPS = 50
MAX_ID_LEN = 64
COORD_LIMIT = 10000

#: Допустимые выравнивания содержимого блока (см. project.ts).
ALLOWED_ALIGN = ('left', 'center', 'right')

#: Типы свойств, которые панель умеет отрисовывать. Всё, чего здесь нет,
#: сервер обязан отвергнуть: неизвестное поле экспорт не разберёт.
ALLOWED_PROP_TYPES = ('text', 'textarea', 'number', 'select', 'boolean', 'color')


def validate_tree(value: Any) -> str | None:
    """Возвращает текст первой ошибки либо None, если дерево корректно."""
    if not isinstance(value, dict):
        return 'tree: ожидается объект'

    width = value.get('width')
    if not isinstance(width, (int, float)) or isinstance(width, bool):
        return 'tree.width: ожидается число'
    if not math.isfinite(width) or width <= 0:
        return 'tree.width: ожидается положительное число'
    if width > COORD_LIMIT:
        return 'tree.width: слишком велико'

    blocks = value.get('blocks')
    if not isinstance(blocks, list):
        return 'tree.blocks: ожидается массив'
    if len(blocks) > MAX_BLOCKS:
        return f'tree.blocks: больше {MAX_BLOCKS} блоков'

    seen: set[str] = set()
    for index, block in enumerate(blocks):
        prefix = f'tree.blocks[{index}]: '
        if not isinstance(block, dict):
            return prefix + 'ожидается объект'

        block_id = block.get('id')
        if not isinstance(block_id, str) or not 0 < len(block_id) <= MAX_ID_LEN:
            return prefix + f'id должен быть строкой 1–{MAX_ID_LEN} символа'
        if block_id in seen:
            return prefix + f'повторяющийся id "{block_id}"'
        seen.add(block_id)

        for key in ('x', 'y', 'width', 'height'):
            coordinate = block.get(key)
            if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool):
                return prefix + f'{key}: ожидается число'
            if not math.isfinite(coordinate):
                return prefix + f'{key}: нечисловое значение'
            if not -COORD_LIMIT <= coordinate <= COORD_LIMIT:
                return prefix + f'{key}: вне диапазона'

        if block['width'] <= 0 or block['height'] <= 0:
            return prefix + 'width и height должны быть положительными'

        # Модуль сверяется с реестром: неизвестный id в базу попасть не
        # может, иначе экспорт (ТЗ п.16.2) не найдёт для него блок.
        module_id = block.get('module')
        if not isinstance(module_id, str) or module_id not in MODULE_IDS:
            return prefix + f'module: неизвестный модуль "{module_id}"'

        label = block.get('label')
        if not isinstance(label, str) or len(label) > MAX_LABEL:
            return prefix + f'label: строка до {MAX_LABEL} символов'

        # Клиентскую проверку можно обойти, поэтому align и content
        # проверяются здесь же: без этого в базу попадали произвольные
        # строки, которые ломали бы экспорт (ТЗ п.16.2).
        align = block.get('align')
        if align is not None:
            if not isinstance(align, str):
                return prefix + 'align: строка'
            if align not in ALLOWED_ALIGN:
                return prefix + f'align: допустимо {", ".join(ALLOWED_ALIGN)}'

        content = block.get('content')
        if content is not None:
            if not isinstance(content, str):
                return prefix + 'content: строка'
            if len(content) > MAX_CONTENT:
                return prefix + f'content: длиннее {MAX_CONTENT} символов'

        error = validate_props(module_id, block.get('props'), prefix + 'props: ')
        if error:
            return error

    error = validate_logic(value.get('logic'))
    if error:
        return error

    error = validate_logic_blocks(value)
    if error:
        return error

    return None


def validate_logic(value: Any) -> str | None:
    """Проверяет граф логики при сохранении документа.

    Проверка здесь, а не только при сборке: иначе человек сохранил бы
    сломанный граф, ушёл, и узнал бы о нём через час — при попытке
    опубликовать сайт.
    """
    if value is None:
        return None
    try:
        from logic.graph import LogicError, validate as validate_graph
        validate_graph(value)
    except LogicError as e:
        # Проблемы перечисляются по одной строкой: список помогает
        # показать их все сразу, а не по одному за сохранение.
        return 'tree.logic: ' + str(e).replace('; ', '; ')
    return None


def validate_props(module_id: str, value: Any, prefix: str) -> str | None:
    """Проверяет свойства блока по схеме его модуля.

    Схема берётся из реестра, поэтому сервер и редактор смотрят в один
    источник. Клиентскую проверку обойти можно, а экспорт (ТЗ п.16.2)
    встретит поле, которого не знает, и упадёт на позапросной сборке.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        return prefix + 'ожидается объект'
    if len(value) > MAX_PROPS:
        return prefix + f'больше {MAX_PROPS} свойств'

    schema = schema_for(module_id)
    if schema is None:
        # Схемы у модуля нет: принимаем только плоские скалярные значения.
        # Произвольная вложенность сюда попадать не должна.
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64:
                return prefix + 'ключ: строка до 64 символов'
            if not isinstance(item, (str, int, float, bool)):
                return f'{prefix}{key}: ожидается скалярное значение'
            if isinstance(item, str) and len(item) > MAX_CONTENT:
                return f'{prefix}{key}: длиннее {MAX_CONTENT} символов'
        return None

    known = {p.name: p for p in schema.props}

    for key, item in value.items():
        prop = known.get(key)
        if prop is None:
            return prefix + f'свойство "{key}" не описано у модуля {module_id}'

        if prop.type == 'number':
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                return f'{prefix}{key}: ожидается число'
            limits = prop.limits or {}
            if 'min' in limits and item < limits['min']:
                return f'{prefix}{key}: меньше {limits["min"]}'
            if 'max' in limits and item > limits['max']:
                return f'{prefix}{key}: больше {limits["max"]}'
        elif prop.type == 'boolean':
            if not isinstance(item, bool):
                return f'{prefix}{key}: ожидается true или false'
        elif prop.type == 'select':
            options = (prop.limits or {}).get('options') or []
            if item not in options:
                return f'{prefix}{key}: допустимо {", ".join(map(str, options))}'
        elif prop.type == 'color':
            if not isinstance(item, str) or len(item) > 32:
                return f'{prefix}{key}: строка до 32 символов'
        elif prop.type in ('text', 'textarea'):
            if not isinstance(item, str):
                return f'{prefix}{key}: строка'
            limit = MAX_LABEL if prop.type == 'text' else MAX_CONTENT
            if len(item) > limit:
                return f'{prefix}{key}: длиннее {limit} символов'

    return None


#: Адрес страницы: строчная латиница, цифры и дефис. Кириллический
#: заголовок транслитерируется при создании, но пришедший от клиента
#: slug проверяется как есть — иначе в URL попали бы пробелы и «?».
PAGE_SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')

#: Служебные адреса: они заняты платформой и файлами пакета.
RESERVED_SLUGS = frozenset({
    'api', 'admin', 'assets', 'static', 'media', 'build-manifest',
    'robots', 'sitemap', 'index', 'service-worker',
})


class PageSerializer(serializers.ModelSerializer):
    """Страница проекта: чтение и запись дерева, адреса и SEO-полей."""

    seoTitle = serializers.CharField(
        source='seo_title', max_length=200, required=False, allow_blank=True,
    )
    seoDescription = serializers.CharField(
        source='seo_description', max_length=300, required=False, allow_blank=True,
    )
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Page
        fields = [
            'id', 'title', 'slug', 'tree', 'seoTitle', 'seoDescription',
            'order', 'version', 'createdAt', 'updatedAt',
        ]
        read_only_fields = ['id', 'version', 'createdAt', 'updatedAt']
        extra_kwargs = {
            'title': {'required': False, 'allow_blank': False},
            'slug': {'required': False},
        }

    def validate_title(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError('название не может быть пустым')
        return value

    def validate_slug(self, value: str) -> str:
        value = value.strip().lower()
        if not PAGE_SLUG_RE.match(value):
            raise serializers.ValidationError(
                'адрес: строчная латиница, цифры и дефис, например "about"'
            )
        if value in RESERVED_SLUGS:
            raise serializers.ValidationError(f'адрес "{value}" занят платформой')
        project = (
            self.instance.project if self.instance is not None
            else self.context.get('project')
        )
        if project is not None:
            duplicates = Page.objects.filter(project=project, slug=value)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError('страница с таким адресом уже есть')
        return value

    def validate_tree(self, value: Any) -> Any:
        error = validate_tree(value)
        if error:
            raise serializers.ValidationError(error)
        return value


class PageSummarySerializer(serializers.ModelSerializer):
    """Строка списка страниц: без дерева, оно тяжёлое."""

    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Page
        fields = ['id', 'title', 'slug', 'order', 'version', 'updatedAt']


class ProjectSerializer(serializers.ModelSerializer):
    """Чтение и запись проекта целиком.

    Клиенту отдаются имена в camelCase (updatedAt, createdAt): тип Project
    в apps/web/src/ui/project.ts объявлен именно так, и расхождение
    приводило к undefined в редакторе.
    """

    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)
    # Список страниц нужен редактору сразу: без него переключатель
    # страниц делал бы второй запрос на каждое открытие проекта.
    pages = serializers.SerializerMethodField()

    class Meta:
        model = Project
        # version обязателен в ответе: клиент предъявляет его при
        # следующем сохранении, и без него проверка конфликта (ТЗ п.3.2)
        # не работает.
        fields = ['id', 'name', 'tree', 'version', 'pages', 'createdAt', 'updatedAt']
        read_only_fields = ['id', 'version', 'created_at', 'updated_at']

    def get_pages(self, obj: Project) -> list[dict[str, Any]]:
        return PageSummarySerializer(
            obj.pages.all(), many=True,
        ).data

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError('название не может быть пустым')
        if len(value) > 200:
            raise serializers.ValidationError('название длиннее 200 символов')
        return value

    def validate_tree(self, value: Any) -> Any:
        error = validate_tree(value)
        if error:
            raise serializers.ValidationError(error)
        return value


class ProjectCreateSerializer(serializers.Serializer):
    """Создание проекта: имя, необязательное дерево и необязательный id."""

    # id разрешён, чтобы стенд создавался с постоянным UUID: редактор
    # при первом запуске обращается к /api/projects/<фиксированный id>/.
    # Без этого поля serializer.save(id=...) молча игнорировал бы его.
    id = serializers.UUIDField(required=False, allow_null=False)
    name = serializers.CharField(max_length=200)
    tree = serializers.JSONField(required=False)

    def validate_tree(self, value: Any) -> Any:
        error = validate_tree(value)
        if error:
            raise serializers.ValidationError(error)
        return value

    def create(self, validated_data: dict) -> Project:
        tree = validated_data.get('tree') or default_tree()
        kwargs: dict[str, Any] = {'name': validated_data['name'], 'tree': tree}
        # id прокидываем явно: поле необязательное, и без этой строки
        # стенд создавался бы со случайным UUID вместо запрошенного.
        if 'id' in validated_data:
            kwargs['id'] = validated_data['id']
        # Владелец приходит из представления (serializer.save(owner=...)),
        # но список полей здесь фиксирован, и без этой строки проект
        # остался бы без владельца: удалить его не смог бы никто.
        if validated_data.get('owner') is not None:
            kwargs['owner'] = validated_data['owner']
        return Project.objects.create(**kwargs)


def validate_logic_blocks(tree: Any) -> str | None:
    """Проверяет, что ноды логики ссылаются на существующие блоки.

    «Показать модуль» с несуществующим блоком выглядит исправно и
    молча не делает ничего: посетитель ничего не увидит, а человек
    будет искать, почему. Проверка при сохранении дешевле, чем
    разгадка через неделю после публикации.
    """
    from logic.graph import extract, is_empty, parse

    raw = extract(tree if isinstance(tree, dict) else {})
    if is_empty(raw):
        return None
    try:
        graph = parse(raw)
    except ValueError:
        # Структурные ошибки уже сообщил validate_logic: смотреть
        # ссылки в непроверяемом графе бессмысленно.
        return None

    known = {
        b.get('id')
        for b in (tree.get('blocks') or [])
        if isinstance(b, dict)
    }
    missing = sorted({
        str(node.props.get('blockId'))
        for node in graph.nodes
        if node.props.get('blockId') and str(node.props.get('blockId')) not in known
    })
    if missing:
        return ('tree.logic: эти блоки не найдены на странице: '
                + ', '.join(missing))
    return None
