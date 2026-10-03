"""Сериализаторы проекта.

Валидация дерева повторяет клиентскую (apps/web/src/ui/project.ts), но
на сервере это обязательно: клиентскую проверку можно обойти, а в базу
не должно попасть ничего, что сломает экспорт (ТЗ п.16.2).
"""

import math
from typing import Any

from rest_framework import serializers

from .models import Project, default_tree
from .module_registry import MODULE_IDS

MAX_BLOCKS = 500
MAX_LABEL = 200
MAX_CONTENT = 5000
MAX_ID_LEN = 64
COORD_LIMIT = 10000

#: Допустимые выравнивания содержимого блока (см. project.ts).
ALLOWED_ALIGN = ('left', 'center', 'right')


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

    return None


class ProjectSerializer(serializers.ModelSerializer):
    """Чтение и запись проекта целиком.

    Клиенту отдаются имена в camelCase (updatedAt, createdAt): тип Project
    в apps/web/src/ui/project.ts объявлен именно так, и расхождение
    приводило к undefined в редакторе.
    """

    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Project
        fields = ['id', 'name', 'tree', 'createdAt', 'updatedAt']
        read_only_fields = ['id', 'created_at', 'updated_at']

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
        return Project.objects.create(**kwargs)
