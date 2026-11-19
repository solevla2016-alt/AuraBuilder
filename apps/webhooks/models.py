"""Вебхуки: подписки проекта на его события.

Вебхук — это обещание «когда с сайтом что-то произойдёт, расскажи моему
сервису». Он принадлежит проекту, а не пользователю: события публикации
и деплоя общие для всех, кто этот проект ведёт.

Событие и доставка разделены намеренно. Событие (projects.ProjectEvent)
отвечает на вопрос «что случилось» и живёт в журнале проекта; доставка
— это попытка рассказать об этом конкретному адресу. Таких адресов
может быть несколько, они падают и повторяются независимо, а журнал
событий при этом остаётся одним.

Payload хранится снимком. Журнал событий ограничен 200 записями, и
ссылка на событие через сутки могла бы вести в пустоту; сервис должен
получать самодостаточное сообщение, даже если повторить его придётся
завтра.
"""

from __future__ import annotations

import secrets
from uuid import uuid4

from django.db import models

from projects.models import Project

#: Сколько вебхуков можно завести на проект. Предел не про деньги, а про
#: время операции: доставка идёт внутри сохранения события, и десяток
#: недоступных адресов превратил бы публикацию в ожидание таймаутов.
MAX_WEBHOOKS = 5

#: Сколько доставок хранится на вебхук. Журнал нужен, чтобы разобрать
#: вчерашний сбой, а не как архив: без границы таблица росла бы с каждым
#: событием публикации.
MAX_DELIVERIES = 100

#: Сколько раз автоматический повтор пробует доставку. Больше — значит
#: адрес, скорее всего, умер, и повторять его каждые пять минут вредно
#: обеим сторонам.
MAX_ATTEMPTS = 3

#: Заголовок подписи. Имя с префиксом продукта: получатель может
#: настроить несколько источников и различить их по заголовку.
SIGNATURE_HEADER = 'X-Aura-Signature'


def new_secret() -> str:
    """Секрет подписи. 32 байта в base64url — 43 символа без пробелов."""

    return secrets.token_urlsafe(32)


class Webhook(models.Model):
    """Подписка проекта на события.

    events — список видов событий; пустой список означает «все». Пустой
    как значение по умолчанию выбран специально: иначе новая подписка
    молча не получала бы события, а новый вид события в продукте не
    доставлялся бы никому, пока каждый не отметит его вручную.
    """

    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='webhooks',
    )
    url = models.URLField('адрес', max_length=500)
    # Секрет нужен получателю, чтобы отличить наш запрос от чужого. Он не
    # даёт доступа к платформе, поэтому хранится как есть: иначе его
    # нельзя было бы показать тому, кто настраивает приёмник. Сменить —
    # один клик, старый сразу перестаёт приниматься.
    secret = models.CharField(
        'секрет подписи', max_length=64, default=new_secret, editable=False,
    )
    events = models.JSONField('события', default=list, blank=True)
    active = models.BooleanField('включён', default=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_webhooks',
    )
    created_at = models.DateTimeField('создан', auto_now_add=True)

    class Meta:
        verbose_name = 'вебхук'
        verbose_name_plural = 'вебхуки'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.project_id}: {self.url}'

    def subscribes_to(self, kind: str) -> bool:
        return not self.events or kind in self.events

    def public_dict(self, latest=None, deliveries=None) -> dict:
        payload = {
            'id': str(self.id),
            'url': self.url,
            'events': list(self.events),
            'active': self.active,
            'secret': self.secret,
            'createdAt': self.created_at.isoformat(),
            'latest': latest.public_dict() if latest is not None else None,
        }
        if deliveries is not None:
            payload['deliveries'] = [item.public_dict() for item in deliveries]
        return payload


class WebhookDelivery(models.Model):
    """Одна попытка доставить событие по адресу вебхука.

    status по умолчанию failed, а не pending: если процесс упал между
    созданием записи и отправкой, честнее показать «не доставлено», чем
    вечно ждать доставку, которой никто не займётся.
    """

    STATUS_OK = 'ok'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_OK, 'Доставлено'),
        (STATUS_FAILED, 'Не доставлено'),
    ]

    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    webhook = models.ForeignKey(
        Webhook,
        on_delete=models.CASCADE,
        related_name='deliveries',
    )
    event_kind = models.CharField('событие', max_length=16)
    #: Идентификатор события журнала. Не FK: события удаляются при
    #: переполнении журнала, а доставка должна оставаться читаемой.
    event_id = models.CharField('событие', max_length=36, blank=True)
    payload = models.JSONField('сообщение')
    status = models.CharField(
        'результат', max_length=8, choices=STATUS_CHOICES,
        default=STATUS_FAILED,
    )
    attempts = models.PositiveSmallIntegerField('попыток', default=0)
    response_code = models.PositiveSmallIntegerField(
        'код ответа', null=True, blank=True,
    )
    # Текст ошибки обрезается: получатель мог ответить страницей на
    # мегабайт, а журнал — не место для чужих ответов.
    error = models.CharField('ошибка', max_length=300, blank=True)
    created_at = models.DateTimeField('создана', auto_now_add=True)
    delivered_at = models.DateTimeField('доставлена', null=True, blank=True)

    class Meta:
        verbose_name = 'доставка вебхука'
        verbose_name_plural = 'доставки вебхуков'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['webhook', '-created_at'],
                name='webhook_delivery_recent',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.webhook_id}: {self.event_kind} — {self.get_status_display()}'

    def public_dict(self) -> dict:
        return {
            'id': str(self.id),
            'event': self.event_kind,
            'status': self.status,
            'attempts': self.attempts,
            'responseCode': self.response_code,
            'error': self.error,
            'createdAt': self.created_at.isoformat(),
            'deliveredAt': (
                self.delivered_at.isoformat() if self.delivered_at else None
            ),
        }
