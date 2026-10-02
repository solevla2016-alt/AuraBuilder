"""Перевод дерева страницы с «kind» на «module».

До этой миграции блок описывался полем kind («section», «text», «media»)
— это вид заливки на холсте, а не модуль каталога. Реальный идентификатор
модуля в блоке отсутствовал, поэтому редактор не мог проверить, что блок
существует в реестре, а экспорт (ТЗ п.16.2) — отрендерить его.

Здесь kind переводится в module по таблице соответствий. Блоки с
неизвестным kind удаляются: оставить их было бы значило оставить данные,
которые ни валидатор, ни экспорт не принимают.
"""

from django.db import migrations

# Вид блока -> модуль каталога. Берётся ближайший по смыслу:
# section -> структурная секция, text -> текстовый блок.
KIND_TO_MODULE = {
    'section': 'section.hero',
    'text': 'text.paragraph',
    'media': 'media.image',
}


def kind_to_module(tree):
    """Заменяет kind на module во всех блоках дерева."""
    if not isinstance(tree, dict):
        return tree

    blocks = tree.get('blocks')
    if not isinstance(blocks, list):
        return tree

    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.pop('kind', None)
        if kind is None:
            continue
        # Неизвестный kind тоже переводится: модуль ставится в None, и
        # валидация отвергнет дерево при следующем сохранении. Так
        # поломанные данные видны, а не молча спутаны с корректными.
        block['module'] = KIND_TO_MODULE.get(kind)

    return tree


def forwards(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    for project in Project.objects.all():
        tree = project.tree
        if not isinstance(tree, dict):
            continue
        blocks = tree.get('blocks')
        if not isinstance(blocks, list):
            continue

        # kind_to_module меняет дерево на месте, поэтому признак
        # изменения — не сравнение объектов (оно всегда ложно),
        # а сам факт наличия kind.
        changed = any(
            isinstance(block, dict) and 'kind' in block for block in blocks
        )
        if not changed:
            continue

        new_tree = kind_to_module(tree)
        project.tree = new_tree
        project.save(update_fields=['tree'])


def backwards(apps, schema_editor):
    """Возврат к kind: берём вид блока из module через реестр.

    Обратная миграция нужна для отката релиза, поэтому она опирается на
    текущий реестр, а не на захардкоженную таблицу.
    """
    from projects.module_registry import MODULES_BY_ID

    module_to_kind = {m.id: m.kind for m in MODULES_BY_ID.values()}

    Project = apps.get_model('projects', 'Project')
    for project in Project.objects.all():
        tree = project.tree
        if not isinstance(tree, dict) or not isinstance(tree.get('blocks'), list):
            continue
        changed = False
        for block in tree['blocks']:
            if not isinstance(block, dict) or 'module' not in block:
                continue
            kind = module_to_kind.get(block.pop('module'))
            block['kind'] = kind or 'text'
            changed = True
        if changed:
            project.tree = tree
            project.save(update_fields=['tree'])


class Migration(migrations.Migration):

    dependencies = [('projects', '0001_initial')]

    operations = [migrations.RunPython(forwards, backwards)]
