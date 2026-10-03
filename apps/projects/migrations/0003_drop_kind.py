"""Удаление поля kind из дерева страницы.

Вид блока на холсте (заливка) — производная величина от модуля: берётся
из реестра по полю module. Хранить его рядом с module означало держать
в базе значение, которое может разойтись с реестром.

Так случилось и на стенде: проект, сохранённый без поля kind, вернулся
в редактор, где текстовый блок перестал считаться текстовым — панель
свойств не показала поле содержимого.

Миграция удаляет ключ из всех деревьев. Обратима не полностью: если
kind лежал не в реестре, восстановить его нечем. Но он и не был нужен:
после миграции код вычисляет вид по module.
"""

from django.db import migrations


def strip_kind(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    for project in Project.objects.all():
        tree = project.tree
        if not isinstance(tree, dict):
            continue
        blocks = tree.get('blocks')
        if not isinstance(blocks, list):
            continue

        changed = False
        for block in blocks:
            if isinstance(block, dict) and 'kind' in block:
                block.pop('kind')
                changed = True

        if changed:
            project.tree = tree
            project.save(update_fields=['tree'])


class Migration(migrations.Migration):

    dependencies = [('projects', '0002_block_module')]

    operations = [migrations.RunPython(strip_kind, migrations.RunPython.noop)]