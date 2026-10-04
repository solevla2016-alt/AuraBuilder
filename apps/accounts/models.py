"""Учётные записи, роли в проекте и журнал действий.

Матрица ролей — ТЗ п.11.1:

* Owner — полный доступ, биллинг, удаление, управление ПДн;
* Admin — настройки, публикация, интеграции;
* Editor — контент, тексты, картинки;
* Dev — API, вебхуки, кастомный код;
* Viewer — только просмотр черновика.

Роль хранится не в проекте, а в связке «пользователь — проект»:
у одного человека разные права в разных проектах, а у проекта
несколько участников. Единственное исключение — Owner: у проекта он
всегда один, и хранить его надо в самом проекте, иначе проект останется
без владельца, то есть без того, кто может его удалить.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    """Роли из ТЗ п.11.1. Значения хранятся в базе как строки."""

    OWNER = 'owner', 'Владелец'
    ADMIN = 'admin', 'Администратор'
    EDITOR = 'editor', 'Редактор'
    DEV = 'dev', 'Разработчик'
    VIEWER = 'viewer', 'Наблюдатель'


class Membership(models.Model):
    """Участие пользователя в проекте с правом по роли."""

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            # Один пользователь — одна роль в проекте. Без этого
            # два участника могли бы получить Viewer и Owner одновременно,
            # и проверка прав зависела бы от порядка строк в базе.
            models.UniqueConstraint(
                fields=['project', 'user'],
                name='unique_membership_per_project',
            ),
        ]
        ordering = ['user_id']

    def __str__(self) -> str:
        return f'{self.user_id} в {self.project_id}: {self.role}'


class AuditLog(models.Model):
    """Журнал действий (ТЗ п.11.2).

    Хранится год: в проекте без входа пользователя к персональным данным
    нельзя доказать, кто их читал. Поэтому запись создаётся на сервере
    при каждом изменении проекта, а не по желанию клиента.
    """

    # Действия хранятся строкой, а не ссылкой на справочник: перечень
    # расширяется вместе с этапами, и миграция на каждый новый тип
    # действия стоила бы дороже, чем строка в журнале.
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_entries',
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='audit_entries',
    )
    # Идентификатор изменённого объекта внутри дерева: дерево — это JSON,
    # и ссылка на конкретный блок в нём нужна журналу, а не БД.
    block_id = models.CharField(max_length=64, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['project', '-created_at'])]

    def __str__(self) -> str:
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.action} ({self.actor_id})'


class UserConsent(models.Model):
    """Согласие на обработку персональных данных (ТЗ п.7.3, 152-ФЗ).

    Требуется логировать само согласие и возможность его отозвать, поэтому
    запись хранит не только факт, но и дату, версию документа и отзыв.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='consents',
    )
    # Версия текста согласия: смена формулировок не должна стирать
    # предыдущие записи, иначе нельзя доказать, на каких условиях
    # человек соглашался.
    document_version = models.CharField(max_length=20, default='1.0')
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-granted_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'document_version'],
                name='unique_consent_per_version',
            ),
        ]

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def __str__(self) -> str:
        return f'согласие v{self.document_version}: {self.active}'