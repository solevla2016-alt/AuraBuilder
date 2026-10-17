"""Модель файла медиатеки проекта."""

from __future__ import annotations

from django.db import models

from projects.models import Project


class Asset(models.Model):
    """Файл, загруженный в проект.

    Файл лежит на диске, а в базе — имя, размер и тип: содержимое
    картинок платформе не нужно, и держать его в базе означало бы
    дублировать мегабайты при каждом экспорте.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='assets',
        verbose_name='Проект',
    )
    name = models.CharField('Имя файла', max_length=120, unique=True)
    original_name = models.CharField('Имя при загрузке', max_length=255, blank=True)
    content_type = models.CharField('Тип', max_length=60)
    size = models.PositiveIntegerField('Размер, байт', default=0)
    created_at = models.DateTimeField('Загружен', auto_now_add=True)

    class Meta:
        verbose_name = 'Файл медиатеки'
        verbose_name_plural = 'Файлы медиатеки'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.original_name or self.name

    def public_dict(self) -> dict:
        from .storage import url_for

        return {
            'id': str(self.id),
            'name': self.name,
            'originalName': self.original_name,
            'contentType': self.content_type,
            'size': self.size,
            'url': url_for(self.project, self.name),
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }