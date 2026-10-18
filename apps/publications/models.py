"""Публикация сайта на инфраструктуре платформы (сценарий 1, ТЗ п.16.3).

Что здесь и почему отдельно от выгрузки. Выгрузка отдаёт архив в
руки человеку, публикация делает сайт доступным по адресу и требует
ответа на вопросы, которых у архива нет: какая версия сейчас
опубликована, что было раньше, отозван ли сайт и сколько к нему
обращаются.

Инфраструктурная часть ТЗ п.16.3 — поддомены, автоматический
сертификат, российский CDN, защита от DDoS, ежедневные бэкапы и
мониторинг — живёт не в приложении. Здесь сделано то, что приложение
обязано: собрать, разложить, переключать версию, отдавать по адресу,
отозвать и хранить резервную копию. Остальное записано в
docs/TZ-GAPS.md как требования к эксплуатации.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

STATE_ACTIVE = 'active'
STATE_WITHDRAWN = 'withdrawn'

STATE_CHOICES = (
    (STATE_ACTIVE, 'Опубликован'),
    (STATE_WITHDRAWN, 'Отозван'),
)

#: Адрес публикации: строчные латинские буквы, цифры и дефис.
#: Кириллица и подчёркивание исключены намеренно: адрес попадает в
#: DNS, заголовки и файлы, где лишние символы ломают молча.
SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$')


def slugify_site_name(name: str) -> str:
    """Человеческое название проекта → безопасный адрес.

    Транслитерация не подставляется: она молча даёт разные адреса для
    похожих названий. Вместо неё используются буквы и цифры, а
    уникальность обеспечивается добавлением короткого суффикса.
    """
    cleaned = ''.join(
        ch if (ch.isascii() and (ch.isalnum() or ch == '-')) else '-'
        for ch in (name or '').lower()
    )
    cleaned = re.sub(r'-+', '-', cleaned).strip('-')[:60].strip('-')
    if not cleaned or not SLUG_RE.match(cleaned):
        # Название без латиницы («Цветы») должно дать адрес, а не отказ:
        # иначе публикация оказывается недоступна половине клиентов.
        cleaned = 'site'
    return cleaned


def publish_root() -> Path:
    root = Path(getattr(settings, 'PUBLISH_ROOT', Path(tempfile_dir()) / 'published'))
    root.mkdir(parents=True, exist_ok=True)
    return root


def tempfile_dir() -> str:
    import tempfile

    return tempfile.gettempdir()


class Site(models.Model):
    """Опубликованный сайт проекта."""

    project = models.OneToOneField(
        'projects.Project', on_delete=models.CASCADE, related_name='site'
    )
    slug = models.SlugField('Адрес', max_length=63, unique=True)
    state = models.CharField(
        'Состояние', max_length=12, choices=STATE_CHOICES, default=STATE_ACTIVE
    )
    current_version = models.ForeignKey(
        'publications.SiteVersion', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='current_for',
    )
    published_at = models.DateTimeField('Опубликован', default=timezone.now)
    withdrawn_at = models.DateTimeField('Отозван', null=True, blank=True)
    # Счётчики нужны для мониторинга доступности (ТЗ п.16.3): без них
    # «сайт работает» остаётся предположением.
    requests = models.PositiveIntegerField('Обращений', default=0)
    last_request_at = models.DateTimeField('Последнее обращение', null=True, blank=True)

    class Meta:
        verbose_name = 'Публикация'
        verbose_name_plural = 'Публикации'
        ordering = ['-published_at']

    def __str__(self) -> str:
        return f'{self.slug} ({self.get_state_display()})'

    @property
    def is_active(self) -> bool:
        return self.state == STATE_ACTIVE

    def url(self) -> str:
        """Адрес публикации.

        В стенде это префикс /sites/, в эксплуатации — поддомен. Формат
        адреса хранится в настройках, чтобы смена схемы раздачи не
        меняла модель.
        """
        base = getattr(settings, 'PUBLICATION_BASE_URL', '').rstrip('/')
        if base:
            return f'{base}/{self.slug}/'
        return f'/sites/{self.slug}/'

    def directory(self) -> Path:
        return publish_root() / 'sites' / self.slug


class SiteVersion(models.Model):
    """Опубликованная версия сайта.

    Хранится рядом с другими, а не заменяет их: откат публикации не
    должен требовать пересборки, а потерянная версия не должна
    исчезать из-за опечатки в редакторе.
    """

    site = models.ForeignKey(
        'publications.Site', on_delete=models.CASCADE, related_name='versions'
    )
    number = models.PositiveIntegerField('Версия документа')
    path = models.CharField('Папка', max_length=300)
    size = models.PositiveIntegerField('Размер, байт', default=0)
    files = models.PositiveIntegerField('Файлов', default=0)
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'Версия публикации'
        verbose_name_plural = 'Версии публикации'
        ordering = ['-number']
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'number'], name='unique_published_version_per_site'
            ),
        ]

    def __str__(self) -> str:
        return f'{self.site.slug}: v{self.number}'

    @property
    def directory(self) -> Path:
        return publish_root() / self.path

    def public_dict(self) -> dict:
        return {
            'number': self.number,
            'size': self.size,
            'files': self.files,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }


class Backup(models.Model):
    """Резервная копия публикации.

    ТЗ п.16.3 требует ежедневных копий: копия делается по таймеру и
    хранится рядом, отдельным каталогом. Хранение копий дольше
    заданного числа означало бы молчаливый рост диска.

    Копий одной версии может быть сколько угодно: ограничение
    «одна копия на версию» делало ежедневные копии невозможными —
    вторая копия того же дня заменяла первую, а каталог первой
    оставался на диске навсегда.
    """

    site = models.ForeignKey(
        'publications.Site', on_delete=models.CASCADE, related_name='backups'
    )
    number = models.PositiveIntegerField('Версия')
    path = models.CharField('Папка', max_length=300)
    size = models.PositiveIntegerField('Размер, байт', default=0)
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'Резервная копия'
        verbose_name_plural = 'Резервные копии'
        ordering = ['-created_at']

    @property
    def directory(self) -> Path:
        return publish_root() / self.path


__all__ = ['Backup', 'Site', 'SiteVersion', 'slugify_site_name']