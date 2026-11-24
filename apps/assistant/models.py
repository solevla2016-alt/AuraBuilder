"""Расход кредитов ИИ и журнал запросов.

Кредиты считаются по календарным месяцам: подписка уже помесячная, и
отдельный «сброс» по дате регистрации только запутал бы — человек не
понял бы, почему остаток не совпадает с платёжным периодом.

Журнал (`AiRequest`) нужен для «понятного расхода»: одной цифры
«израсходовано» мало, когда непонятно, какое действие её съело. Журнал
при этом не является источником остатка — остаток хранится в
`CreditPeriod`, потому что суммирование всей истории на каждый запрос
росло бы вместе с историей.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class CreditPeriod(models.Model):
    """Израсходованные кредиты одного пользователя за месяц.

    Строка на пользователя и период, а не одна строка на подписку:
    прошлые месяцы нужны для истории, а текущий — для быстрой проверки
    остатка. Счёт идёт по владельцу проекта, как и остальные квоты:
    приглашённый редактор тратит остаток владельца, но не свой — иначе
    общий проект стал бы способом обойти личный лимит.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_credit_periods',
        verbose_name='пользователь',
    )
    #: Период в формате ГГГГ-ММ. Строка, а не дата: границей служит
    #: календарный месяц, и часовой пояс здесь не должен менять ответ.
    period = models.CharField('период', max_length=7)
    used = models.PositiveIntegerField('израсходовано', default=0)
    updated_at = models.DateTimeField('обновлено', auto_now=True)

    class Meta:
        verbose_name = 'кредиты ИИ за период'
        verbose_name_plural = 'кредиты ИИ по периодам'
        ordering = ['-period']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'period'],
                name='unique_ai_credit_period',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.user_id} {self.period}: {self.used}'


class AiRequest(models.Model):
    """Один запрос к помощнику.

    Хранится и автор запроса, и тот, с кого списаны кредиты: на общем
    проекте это разные люди, и в журнале должно быть видно, кто
    израсходовал чужой остаток.
    """

    #: Кто платит: владелец проекта (или сам пользователь без проекта).
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_requests',
        verbose_name='плательщик',
    )
    #: Кто нажал кнопку. null — запрос сделан до появления этой связи.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_actions',
        verbose_name='автор запроса',
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ai_requests',
        verbose_name='проект',
    )
    action = models.CharField('действие', max_length=32)
    provider = models.CharField('провайдер', max_length=24)
    credits = models.PositiveSmallIntegerField('кредиты', default=0)
    period = models.CharField('период', max_length=7)
    #: Описание от пользователя. Хранится, чтобы можно было разобрать
    #: спорный расход; содержимое проекта сюда не попадает.
    prompt = models.TextField('описание', blank=True)
    result = models.JSONField('результат', default=dict, blank=True)
    created_at = models.DateTimeField('создан', auto_now_add=True)

    class Meta:
        verbose_name = 'запрос к ИИ'
        verbose_name_plural = 'запросы к ИИ'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'period']),
            models.Index(fields=['project', '-created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.action} — {self.credits} кр.'


__all__ = ['AiRequest', 'CreditPeriod']
