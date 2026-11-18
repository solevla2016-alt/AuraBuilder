"""Прогресс Академии: какие уроки пользователь отметил пройденными.

Отметка ставится вручную. Автоматическая проверка по состоянию проекта
звучала бы заманчиво, но «создал страницу» не значит «понял, как её
вести»: человек мог нажать кнопку случайно. Поэтому прогресс — это
решение пользователя, а не догадка платформы.

Прогресс принадлежит пользователю, а не проекту: уроки общие, и
переключение между проектами не должно обнулять обучение.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class LessonProgress(models.Model):
    """Один пройденный урок одного пользователя."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='academy_progress',
    )
    #: Идентификатор из content.LESSONS. Строка, а не FK: уроки живут в
    #: коде, и таблица не должна требовать миграции при каждом новом уроке.
    lesson_id = models.CharField('урок', max_length=64)
    completed_at = models.DateTimeField('пройден', auto_now_add=True)

    class Meta:
        verbose_name = 'пройденный урок'
        verbose_name_plural = 'прогресс Академии'
        ordering = ['-completed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'lesson_id'],
                name='unique_academy_lesson_per_user',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.user_id}: {self.lesson_id}'
