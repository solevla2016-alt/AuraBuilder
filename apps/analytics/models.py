"""Аналитика опубликованных сайтов и заявки с форм.

Что здесь хранится и почему именно так. Просмотры и источники — не
журнал посещений, а суточные суммы: для ответа «сколько людей пришло и
откуда» не нужен список адресов посетителей, а хранение такого списка
сделало бы платформу хранилищем персональных данных без пользы для
владельца сайта. Заявки, наоборот, хранятся по одной: это данные,
которые владелец сайта обязан получить, и потерять их нельзя.

Аналитика считается только у сайтов, которые раздаёт платформа.
Статический пакет (ТЗ п.16.4) остаётся без счётчиков и работает без
неё: вставлять в него обращение к платформе значило бы сломать
требование автономности.
"""

from __future__ import annotations

import uuid

from django.db import models


class PageView(models.Model):
    """Суточная сумма просмотров одной страницы сайта."""

    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    site = models.ForeignKey(
        'publications.Site',
        on_delete=models.CASCADE,
        related_name='page_views',
        verbose_name='Сайт',
    )
    day = models.DateField('День')
    path = models.CharField('Страница', max_length=200, default='/')
    views = models.PositiveIntegerField('Просмотры', default=0)

    class Meta:
        verbose_name = 'Просмотры страницы'
        verbose_name_plural = 'Просмотры страниц'
        ordering = ['-day', '-views']
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'day', 'path'],
                name='unique_page_view_per_day',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.site_id} {self.day} {self.path}: {self.views}'


class TrafficSource(models.Model):
    """Суточная сумма просмотров по источнику перехода.

    Источник — это `utm_source`, если он есть, иначе домен реферера.
    Полный адрес перехода не хранится: он может содержать поисковый
    запрос, а для отчёта «откуда пришли» достаточно домена.
    """

    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    site = models.ForeignKey(
        'publications.Site',
        on_delete=models.CASCADE,
        related_name='sources',
        verbose_name='Сайт',
    )
    day = models.DateField('День')
    source = models.CharField('Источник', max_length=60, default='direct')
    views = models.PositiveIntegerField('Просмотры', default=0)

    class Meta:
        verbose_name = 'Источник перехода'
        verbose_name_plural = 'Источники переходов'
        ordering = ['-day', '-views']
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'day', 'source'],
                name='unique_source_per_day',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.site_id} {self.day} {self.source}: {self.views}'


class FormSubmission(models.Model):
    """Заявка, отправленная с формы опубликованного сайта.

    Поля хранятся как пришли, без приведения к схеме: формы собираются
    из блоков, и заранее известного набора полей у платформы нет.
    Значения показываются в редакторе экранированными, поэтому текст
    заявки не может стать разметкой.
    """

    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    site = models.ForeignKey(
        'publications.Site',
        on_delete=models.CASCADE,
        related_name='submissions',
        verbose_name='Сайт',
    )
    page = models.CharField('Страница', max_length=200, default='/')
    source = models.CharField('Источник', max_length=60, blank=True, default='')
    data = models.JSONField('Поля заявки', default=dict)
    created_at = models.DateTimeField('Получена', auto_now_add=True)

    class Meta:
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['site', '-created_at'],
                name='analytics_submission_recent',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.site_id} {self.created_at:%d.%m.%Y %H:%M}'

    def public_dict(self) -> dict:
        return {
            'id': str(self.id),
            'page': self.page,
            'source': self.source,
            'createdAt': self.created_at.isoformat(),
            'fields': self.data,
        }


__all__ = ['FormSubmission', 'PageView', 'TrafficSource']
