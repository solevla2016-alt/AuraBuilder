"""Экспорт и импорт конфигурации проекта (ТЗ п.16.7).

Формат — один файл `project.json` со всей структурой: дерево страницы,
история версий, узлы данных с записями и стили компонентов. Он
нужен для переезда на другой аккаунт и для резервной копии, поэтому
импорт восстанавливает проект целиком, а не только текущее дерево.

Что в файл не попадает: пароли от серверов (ADR-0006), учётные данные
интеграций и всё, что принадлежит не проекту, а человеку. Перенос
доступов — отдельное действие, и молча положить чужой пароль в файл
значило бы раздать его всем, кто этот файл получил.

По тарифам сценарий доступен всем (ТЗ п.17.1), поэтому экспорт
конфигурации не требует права публикации: это чтение своего проекта,
а не выдача готового сайта.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.db import transaction

from component_library.models import ComponentStyle
from data_sources.models import DataRecord, DataSource

from .models import DocumentVersion, Project
from .module_registry import MODULE_IDS

#: Версия формата. Растёт, когда меняется структура файла; импорт
#: отказывает от более новой версии, а не гадает о содержимом.
FORMAT = 'aurabuilder.project'
FORMAT_VERSION = 1


class ConfigError(Exception):
    """Файл конфигурации не подходит для импорта."""


def _iso(value) -> str | None:
    if not value:
        return None
    if hasattr(value, 'astimezone'):
        return value.astimezone(UTC).isoformat()
    return str(value)


def dump_project(project: Project) -> dict[str, Any]:
    """Полная конфигурация проекта одним словарём."""
    versions = list(project.versions.order_by('number'))
    sources = list(DataSource.objects.filter(project=project).prefetch_related('records'))

    return {
        'format': FORMAT,
        'formatVersion': FORMAT_VERSION,
        'exportedAt': datetime.now(UTC).isoformat(),
        # Идентификатор проекта не переносится: на другом аккаунте он
        # не значит ничего, а по нему можно было бы спутать два
        # экспорта одного проекта.
        'project': {
            'name': project.name,
            'width': int(project.tree.get('width', 1200) if isinstance(project.tree, dict) else 1200),
            'version': project.version,
            'tree': project.tree,
        },
        'versions': [
            {
                'number': v.number,
                'label': v.label,
                'tree': v.tree,
                'createdAt': _iso(v.created_at),
                'author': v.author.username if v.author_id else None,
            }
            for v in versions
        ],
        'dataSources': [
            {
                'name': s.name,
                'key': s.key,
                'description': s.description,
                'fields': s.fields,
                'records': [
                    {'data': r.data} for r in s.records.order_by('position', 'created_at')
                ],
            }
            for s in sources
        ],
        'componentStyles': [
            {'kind': style.kind, 'tokens': style.tokens}
            for style in ComponentStyle.objects.filter(project=project).order_by('kind')
        ],
    }


def to_json(project: Project) -> str:
    return json.dumps(dump_project(project), ensure_ascii=False, indent=2)


def _require(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ConfigError('Файл должен содержать объект JSON.')
    if payload.get('format') != FORMAT:
        raise ConfigError('Это не файл конфигурации AuraBuilder.')
    version = payload.get('formatVersion')
    if not isinstance(version, int):
        raise ConfigError('В файле не указан номер версии формата.')
    if version > FORMAT_VERSION:
        raise ConfigError(
            f'Файл сохранён более новой версией платформы ({version}). '
            'Обновите AuraBuilder, чтобы импортировать его.'
        )
    return payload


def _check_tree(tree: Any, limits: dict) -> dict:
    """Дерево проверяется до сохранения.

    Импорт создаёт проект из чужого файла: без проверок чужой или
    повреждённый JSON занял бы место в базе и положил бы редактор.
    """
    if not isinstance(tree, dict):
        raise ConfigError('Дерево страницы должно быть объектом.')
    blocks = tree.get('blocks')
    if not isinstance(blocks, list):
        raise ConfigError('В дереве нет списка блоков.')
    if len(blocks) > limits['MAX_MODULES_PER_PROJECT']:
        raise ConfigError(
            f'В файле {len(blocks)} блоков, а проект вмещает '
            f'{limits["MAX_MODULES_PER_PROJECT"]}.'
        )

    known = set(MODULE_IDS)
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ConfigError(f'Блок {index + 1} описан неверно.')
        module = block.get('module')
        if module not in known:
            raise ConfigError(
                f'Блок {index + 1}: модуль «{module}» неизвестен каталогу. '
                'Файл сохранён другой версией платформы?'
            )
        if not isinstance(block.get('id'), str) or not block['id']:
            raise ConfigError(f'У блока {index + 1} нет идентификатора.')

    return tree


@transaction.atomic
def import_project(owner, payload: Any) -> Project:
    """Создаёт проект из файла конфигурации."""
    data = _require(payload)
    limits = settings.LIMITS

    project_data = data.get('project')
    if not isinstance(project_data, dict):
        raise ConfigError('В файле нет описания проекта.')
    name = str(project_data.get('name') or '').strip()[:200]
    if not name:
        raise ConfigError('У проекта должно быть имя.')

    count = Project.objects.filter(owner=owner).count()
    if count >= limits['MAX_PROJECTS_PER_USER']:
        raise ConfigError(
            f'У вас уже {count} проектов, а аккаунт вмещает '
            f'{limits["MAX_PROJECTS_PER_USER"]}.'
        )

    width = project_data.get('width', 1200)
    if not isinstance(width, int) or not 320 <= width <= 3840:
        raise ConfigError('Ширина страницы должна быть числом от 320 до 3840.')

    tree = _check_tree(project_data.get('tree'), limits)
    tree = {**tree, 'width': width}

    project = Project.objects.create(owner=owner, name=name, tree=tree)

    # История версий: без неё «полный бэкап» был бы половиной бэкапа,
    # и откатиться после переезда было бы нечем.
    for item in data.get('versions') or []:
        if not isinstance(item, dict):
            continue
        number = item.get('number')
        if not isinstance(number, int) or number < 1:
            continue
        version_tree = item.get('tree')
        if not isinstance(version_tree, dict):
            continue
        DocumentVersion.objects.create(
            project=project,
            number=number,
            tree=_check_tree(version_tree, limits),
            label=str(item.get('label') or '')[:200],
            author=owner,
        )

    for item in data.get('dataSources') or []:
        if not isinstance(item, dict):
            continue
        fields = item.get('fields')
        records = item.get('records') or []
        if not isinstance(fields, list) or not fields:
            continue
        if len(records) > limits['MAX_RECORDS_PER_SOURCE']:
            raise ConfigError(
                f'В источнике «{item.get("name")}» {len(records)} записей, '
                f'а вмещается {limits["MAX_RECORDS_PER_SOURCE"]}.'
            )
        key = str(item.get('key') or '')[:60]
        if not key or DataSource.objects.filter(project=project, key=key).exists():
            key = _free_key(project, key)
        source = DataSource.objects.create(
            project=project,
            name=str(item.get('name') or 'Источник')[:200],
            key=key,
            description=str(item.get('description') or '')[:400],
            fields=fields,
        )
        for position, record in enumerate(records):
            data_cell = record.get('data') if isinstance(record, dict) else None
            if not isinstance(data_cell, dict):
                continue
            DataRecord.objects.create(
                source=source, data=data_cell, position=position
            )

    for item in data.get('componentStyles') or []:
        if not isinstance(item, dict):
            continue
        kind = item.get('kind')
        tokens = item.get('tokens')
        if kind not in ('section', 'text', 'media') or not isinstance(tokens, dict):
            continue
        ComponentStyle.objects.update_or_create(
            project=project, kind=kind, defaults={'tokens': tokens}
        )

    latest = project.versions.order_by('-number').first()
    project.version = max(int(project_data.get('version') or 1),
                          latest.number if latest else 1)
    project.save(update_fields=['version'])
    return project


def _free_key(project: Project, key: str) -> str:
    """Ключ источника уникален внутри проекта.

    Два источника с одинаковым ключом сломали бы привязку блоков: они
    бы смотрели в один узел, и править пришлось бы вручную.
    """
    candidate = key
    index = 2
    while DataSource.objects.filter(project=project, key=candidate).exists():
        candidate = f'{key}-{index}'
        index += 1
    return candidate


__all__ = ['ConfigError', 'FORMAT_VERSION', 'dump_project', 'import_project', 'to_json']