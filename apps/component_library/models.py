"""Стили компонентов проекта (библиотека компонентов, ТЗ п.3.1).

Замысел: «Изюминка №1» — пользователь меняет стиль один раз, а
компоненты на всех страницах обновляются сами. Поэтому здесь не
хранится оформление отдельных блоков, а стиль вида компонента целиком:
секция, текст, медиа.

Отличие от свойств блока видно на конкретном примере. Кнопка в
`section.hero` и кнопка в `action.button` рисуются разными кодами
модулей, но выглядят для посетителя одним и тем же компонентом.
Стиль кнопки, заданный здесь, должен менять обе — иначе «изменение
одного стиля обновляет их на всех страницах» окажется untrue: модулей
65, и править их по одному нельзя.

Поэтому вид компонента (kind) — не вид блока, а роль: в редакторе их
три, и три хватает, чтобы правило «меняешь один раз — меняется везде»было
выполнимо на текущем этапе. Расширение на четыре-пять ролей не
потребует миграции: ключ в БД остаётся строкой.

Стиль хранится как словарь токенов, а не набор столбцов: набор
столбцов означал бы миграцию на каждое новое свойство, а словарь
проверяется списком допустимых ключей в сериализаторе.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

#: Виды компонентов. Названия совпадают с ModuleKind реестра: роль
#: компонента и роль блока в макете — одно и то же.
COMPONENT_KINDS = (
    ('section', 'Секция'),
    ('text', 'Текст'),
    ('media', 'Медиа'),
)

#: Допустимые ключи стиля и их значения по умолчанию.
#:
#: Числа ограничены сверху осмысленно: скругление в 200 пикселей и поля
#: в 400 не делают компонент красивее, но ломают вёрстку при экспорте,
#: где размеры считаются по-другому.
TOKEN_LIMITS: dict[str, tuple[int, int]] = {
    'radius': (0, 32),
    'padding': (0, 96),
    'weight': (400, 800),
    'border': (0, 4),
}

#: Цветовые ключи: значение — имя токена палитры или #RRGGBB.
COLOR_KEYS = ('background', 'text')

DEFAULT_TOKENS: dict[str, dict[str, object]] = {
    # Значения по умолчанию совпадают с тем, что холст рисовал до
    # появления библиотеки: пустая библиотека не должна менять внешний
    # вид уже собранных страниц.
    'section': {
        'background': 'panel',
        'text': 'textPrimary',
        'radius': 8,
        'padding': 20,
        'weight': 500,
        'border': 1,
    },
    'text': {
        'background': 'canvas',
        'text': 'textPrimary',
        'radius': 0,
        'padding': 8,
        'weight': 400,
        'border': 0,
    },
    'media': {
        'background': 'canvas',
        'text': 'textSecondary',
        'radius': 8,
        'padding': 12,
        'weight': 400,
        'border': 1,
    },
}


def default_tokens(kind: str) -> dict[str, object]:
    return dict(DEFAULT_TOKENS.get(kind, {}))


class ComponentStyle(models.Model):
    """Стиль одного вида компонента в пределах проекта."""

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='component_styles',
    )
    kind = models.CharField('компонент', max_length=16, choices=COMPONENT_KINDS)
    # {'background': 'panel', 'text': 'textPrimary', 'radius': 8, ...}
    tokens = models.JSONField('токены', default=dict)
    created_at = models.DateTimeField('создан', auto_now_add=True)
    updated_at = models.DateTimeField('изменён', auto_now=True)

    class Meta:
        constraints = [
            # Один стиль на вид компонента в проекте: два конкурирующих
            # стиля секции означали бы, что страницы «переезжают» при
            # сохранении, и объяснить пользователю, какой из них
            # действующий, было бы нечем.
            models.UniqueConstraint(
                fields=['project', 'kind'],
                name='unique_component_style_per_project',
            ),
        ]
        ordering = ['kind']

    def clean(self) -> None:
        if not self.tokens:
            raise ValidationError({'tokens': 'Стиль не может быть пустым.'})
        unknown = set(self.tokens) - set(TOKEN_LIMITS) - set(COLOR_KEYS)
        if unknown:
            raise ValidationError(
                {'tokens': f'Неизвестные свойства стиля: {", ".join(sorted(unknown))}.'}
            )
        for name, (low, high) in TOKEN_LIMITS.items():
            if name not in self.tokens:
                continue
            value = self.tokens[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError({'tokens': f'{name}: нужно целое число.'})
            if not low <= value <= high:
                raise ValidationError({'tokens': f'{name}: от {low} до {high}.'})

    def __str__(self) -> str:
        return f'{self.project_id}: {self.kind}'