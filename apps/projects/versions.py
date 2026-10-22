"""Снимки версий документа: создание, обрезка, восстановление.

Вынесено из views.py не ради порядка, а ради повторного
использования: правило «сколько версий храним» должно быть одно и
для автосохранения, и для ручной отметки, иначе история наполнялась
бы мимо правила.
"""

from __future__ import annotations

from typing import Any

from accounts.serializers import audit
from .models import DocumentVersion, Page, Project

#: Сколько снимков хранится на проект.
#:
#: Число выбрано по памяти, а не по вкусу: снимок — это дерево целиком,
#: и при тарифах с ограничением хранилища (п.17.1) сотня версий одного
#: проекта съела бы место, которое отведено десяткам проектов. Старые
#: снимки удаляются молча: восстановиться из них уже нельзя, и оставлять
#: их в интерфейсе значило бы показывать недоступное действие.
MAX_VERSIONS = 50


def _pages_snapshot(project: Project) -> list[dict[str, Any]]:
    """Дополнительные страницы в виде, пригодном для JSON-снимка."""

    return [
        {
            'title': page.title,
            'slug': page.slug,
            'tree': page.tree,
            'seo_title': page.seo_title,
            'seo_description': page.seo_description,
            'order': page.order,
        }
        for page in project.pages.order_by('order', 'created_at')
    ]


def snapshot(project: Project, tree: dict[str, Any], author=None, label: str = '',
             pages: list[dict[str, Any]] | None = None) -> DocumentVersion:
    """Снимок дерева с номером на единицу больше текущей версии проекта.

    Номер считается от версии проекта, а не от последнего снимка: после
    обрезки истории последнего снимка может не быть, и версия поехала бы
    назад — документ, который вернули к старому состоянию, получил бы
    номер меньше того, что был.

    Снимок включает и дополнительные страницы: иначе восстановление
    вернуло бы только главную, а всё, что человек сделал на остальных,
    пропало бы без предупреждения.
    """

    version = DocumentVersion.objects.create(
        project=project,
        number=project.version + 1,
        tree=tree,
        pages=_pages_snapshot(project) if pages is None else pages,
        author=author,
        label=label,
    )
    prune_versions(project)
    return version


def prune_versions(project: Project) -> None:
    """Оставить последние MAX_VERSIONS снимков."""

    extra = list(
        DocumentVersion.objects.filter(project=project)
        .order_by('-number')
        .values_list('id', flat=True)[MAX_VERSIONS:]
    )
    if extra:
        DocumentVersion.objects.filter(id__in=extra).delete()


def restore(request, project: Project, version: DocumentVersion) -> dict[str, Any]:
    """Вернуть дерево версии и сохранить результат как новую версию.

    История не переписывается: восстановление само становится версией,
    поэтому «отменить восстановление» — это восстановление предыдущей.
    """

    project.tree = version.tree
    project.save(update_fields=['tree', 'updated_at'])

    # Страницы возвращаются вместе с главной: снимок описывает документ
    # целиком, и оставлять текущие страницы значило бы собрать состояние,
    # которого никогда не было.
    project.pages.all().delete()
    rows = version.pages if isinstance(version.pages, list) else []
    Page.objects.bulk_create([
        Page(
            project=project,
            title=str(item.get('title') or 'Страница')[:200],
            slug=str(item.get('slug') or 'page')[:80],
            tree=item.get('tree') if isinstance(item.get('tree'), dict) else {},
            seo_title=str(item.get('seo_title') or '')[:200],
            seo_description=str(item.get('seo_description') or '')[:300],
            order=item.get('order') if isinstance(item.get('order'), int) else 0,
        )
        for item in rows
        if isinstance(item, dict)
    ])

    created = snapshot(project, version.tree, author=request.user, label=f'Восстановлено из версии {version.number}')
    project.version = created.number
    project.save(update_fields=['version', 'updated_at'])
    audit(request, 'project.restore', project, str(version.number))
    return created
