"""Медиатека в сборке пакета.

Файлы кладутся в пакет и ссылки на них заменяются локальными. Без
замены экспорт получался бы битым: страница ссылалась бы на адрес
платформы, а человек унёс пакет на свой хостинг и увидел пустые
картинки.

Замена идёт по точному адресу файла медиатеки. Простой замены
подстроки было бы достаточно, но она задела бы ссылку внутри
текста; здесь заменяются только целые значения, которые действительно
указывают на файл проекта.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from projects.models import Project

from .models import Asset
from .storage import project_dir, url_for

#: Куда кладутся картинки в пакете. Префикс assets/img совпадает с
#: тем, как их раскладывает сборщик ассетов (ТЗ п.16.2).
PACK_DIR = 'assets/img'

#: Содержимое файла пакета: текст или байты картинки.
FileContent = str | bytes


def _html_files(files: dict[str, FileContent]) -> list[str]:
    return [name for name in files if name.endswith('.html')]


def collect(project: Project, files: dict[str, FileContent],
            tree: dict | None = None) -> dict[str, list[str]]:
    """Кладёт файлы медиатеки в пакет и переписывает ссылки.

    Возвращает отчёт: что положено и что осталось ссылкой на
    платформу. Отчёт попадает в build-manifest.json, и незакрытая
    ссылка видна в сборке, а не у посетителя.

    Файлы кладутся в пакет по строкам проекта, а не по ссылкам из
    дерева: ссылка может вести на удалённый файл, и такой проект
    должен собраться с честным предупреждением, а не падать.
    """
    assets = list(Asset.objects.filter(project=project)[:200])
    source_dir = project_dir(project)
    packed: list[str] = []
    # Адрес платформы → путь в пакете. Порядок от длинного к
    # короткому не нужен: подставляем по точному совпадению.
    mapping: dict[str, str] = {}

    for asset in assets:
        path = source_dir / asset.name
        if not path.is_file():
            # Запись осталась, а файла нет: база и диск разошлись.
            # Молча пропустить нельзя — ссылка на файл уедет в пакет
            # и сломается у заказчика, поэтому файл попадает в отчёт.
            continue
        target = f'{PACK_DIR}/{asset.name}'
        files[target] = (path.read_text(encoding='utf-8')
                         if _is_text(asset.content_type) else path.read_bytes())
        packed.append(target)
        mapping[url_for(project, asset.name)] = target
        mapping[f'/api/projects/{project.id}/assets/{asset.name}/file/'] = target

    if mapping:
        for name in _html_files(files):
            content = files[name]
            if isinstance(content, str):
                files[name] = _rewrite(content, mapping)

    external = _remaining(files, mapping)
    return {'packed': sorted(packed), 'external': sorted(external)}


def _is_text(content_type: str) -> bool:
    # SVG остаётся текстом: так его можно перепроверить и показать
    # в редакторе, а читать его как байты нельзя.
    return content_type.startswith('text/') or content_type == 'image/svg+xml'


def _rewrite(html: str, mapping: dict[str, str]) -> str:
    """Заменяет ссылки на файлы медиатеки локальными путями."""
    for source, target in mapping.items():
        # Кавычки вокруг значения не трогаются: меняется только сам
        # адрес, и разметка остаётся валидной.
        html = html.replace(source, target)
    return html


def _remaining(files: dict[str, FileContent],
               mapping: dict[str, str]) -> set[str]:
    """Ссылки на медиатеку, которые не нашлись файла.

    Обычно это файл, удалённый после того, как его вставили в блок.
    Молча пропустить такое нельзя: на сайте останется пустая
    картинка, а человек узнает об этом от посетителя.
    """
    pattern = re.compile(r'/api/projects/[^"\')\s]+/assets/[^"\')\s]+/file/')
    missing: set[str] = set()
    for name, content in files.items():
        if not isinstance(content, str) or not name.endswith('.html'):
            continue
        for url in pattern.findall(content):
            if url not in mapping:
                missing.add(url)
    return missing


def manifest_entry(report: dict) -> dict:
    return {
        'count': len(report.get('packed', [])),
        'missing': report.get('external', []),
    }


__all__ = ['PACK_DIR', 'collect', 'manifest_entry']