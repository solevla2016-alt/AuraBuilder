"""Модель проекта и дерева страницы.

ТЗ п.3.2: состояние проекта хранится в Control Plane.

Дерево блоков хранится в JSONField: структура будет меняться вместе
с каталогом модулей (docs/MODULE-CATALOG.md), и реляционная разбивка
сейчас дала бы преждевременную фиксацию схемы. Валидация — на входе
в API, а не на уровне БД: браузеру доверять нельзя.
"""

from uuid import uuid4

from django.db import models


def default_tree() -> dict:
    """Дерево нового проекта.

    Временная структура до появления реестра модулей этапа 3.
    """
    return {
        'width': 720,
        'blocks': [
            {'id': 'b1', 'x': 40, 'y': 40, 'width': 640, 'height': 200,
             'kind': 'section', 'label': 'Первый экран'},
            {'id': 'b2', 'x': 40, 'y': 264, 'width': 640, 'height': 64,
             'kind': 'text', 'label': 'Заголовок'},
            {'id': 'b3', 'x': 40, 'y': 352, 'width': 300, 'height': 180,
             'kind': 'media', 'label': 'Изображение'},
            {'id': 'b4', 'x': 364, 'y': 352, 'width': 316, 'height': 180,
             'kind': 'text', 'label': 'Описание'},
        ],
    }


class Project(models.Model):
    """Проект пользователя.

    Идентификатор — UUID: он попадает в URL публикации и в архив
    экспорта, поэтому перечисляющийся int не подходит (ТЗ п.16.2).
    """

    # default обязателен: при editable=False Django не генерирует значение,
    # и вставка падала бы с «NOT NULL constraint failed: projects_project.id».
    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    name = models.CharField('название', max_length=200)
    tree = models.JSONField('дерево страницы', default=default_tree)
    created_at = models.DateTimeField('создан', auto_now_add=True)
    updated_at = models.DateTimeField('изменён', auto_now=True)

    class Meta:
        verbose_name = 'проект'
        verbose_name_plural = 'проекты'
        ordering = ['-updated_at']

    def __str__(self) -> str:
        return self.name
