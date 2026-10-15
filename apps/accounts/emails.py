"""Письма платформы: восстановление пароля, подтверждение email.

Отправка идёт через основной SMTP (Яндекс 360) с автоматическим
переключением на локальный relay после трёх ошибок подряд (ТЗ
п.13.1). Переключение нужно потому, что недоступность почты не должна
превращать возможность восстановить пароль в отказ: письмо о пароле —
это письмо, без которого человек теряет доступ к своей работе.

Счётчик ошибок лежит в кэше, а не в памяти процесса: при нескольких
репликах локальный счётчик сбрасывал бы общий и переключение
срабатывало бы только внутри одного воркера.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger(__name__)

#: Сколько ошибок подряд переключают отправку на резервный канал.
FAILOVER_THRESHOLD = 3

#: Ключи состояния отправки в кэше. Префикс общий для всех писем:
#: решает не «какое письмо», а «работает ли канал».
STATE_KEY = 'email:failures'
RECOVERED_KEY = 'email:recovered'


@dataclass(frozen=True)
class DeliveryResult:
    """Что получилось с письмом."""

    sent: bool
    #: Основной канал, резервный или ни один.
    channel: str
    error: str = ''

    def __bool__(self) -> bool:
        return self.sent


def _connection(alias: str = 'default'):
    """Соединение по имени настройки EMAIL_BACKEND_<alias>."""
    return get_connection(alias=alias)


def _failover_backend() -> str:
    return getattr(settings, 'EMAIL_FALLBACK_BACKEND',
                   'django.core.mail.backends.locmem.EmailBackend')


def _fallback_connection():
    from django.utils.module_loading import import_string

    backend = import_string(_failover_backend())
    return backend(fail_silently=False)


def failures() -> int:
    return int(cache.get(STATE_KEY, 0) or 0)


def _note_failure() -> int:
    count = failures() + 1
    cache.set(STATE_KEY, count)
    return count


def _note_success() -> None:
    if failures():
        logger.warning('SMTP восстановился после %s ошибок', failures())
    cache.delete(STATE_KEY)
    cache.delete(RECOVERED_KEY)


def on_failover() -> bool:
    """Переключаться ли на резервный канал прямо сейчас."""
    return failures() >= FAILOVER_THRESHOLD


def _send(message: EmailMessage, use_fallback: bool) -> DeliveryResult:
    if use_fallback:
        try:
            message.connection = _fallback_connection()
            message.send()
        except Exception as e:  # noqa: BLE001 — причина в тексте для журнала
            logger.error('резервный канал тоже не работает: %s', e)
            return DeliveryResult(False, 'fallback', str(e))
        cache.set(RECOVERED_KEY, True, 3600)
        return DeliveryResult(True, 'fallback')

    try:
        message.connection = _connection()
        message.send()
    except Exception as e:  # noqa: BLE001 — причина попадает в счётчик
        count = _note_failure()
        logger.warning('письмо не отправлено (%s), ошибок подряд: %s', e, count)
        return DeliveryResult(False, 'primary', str(e))
    _note_success()
    return DeliveryResult(True, 'primary')


def send_mail(subject: str, body: str, to: list[str], *,
              fail_silently: bool = True) -> DeliveryResult:
    """Отправляет письмо, при сбое основного канала — резервному.

    Исключение наружу не выходит: вызывающий код решает, что делать с
    недоступной почтой, и молча проглоченная ошибка здесь сделала бы
    вид, что письмо ушло.
    """
    message = EmailMessage(
        subject=subject, body=body,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@local'),
        to=list(to),
    )

    if not on_failover():
        result = _send(message, use_fallback=False)
        if result.sent:
            return result
        # Три ошибки подряд переводят канал на резервный; с первого
        # раза переключение было бы реакцией на единичный сбой.
        if failures() < FAILOVER_THRESHOLD:
            return result

    return _send(message, use_fallback=True)


def reset_password_body(link: str, ttl_minutes: int) -> str:
    """Текст письма восстановления пароля.

    Письмо говорит и про срок, и про то, что делать, если запрос был
    не нужен: человек не должен гадать, не истекла ли ссылка.
    """
    return (
        'Здравствуйте!\n\n'
        'Мы получили запрос на восстановление пароля в AuraBuilder.\n'
        'Чтобы задать новый пароль, откройте ссылку:\n\n'
        f'{link}\n\n'
        f'Ссылка действует {ttl_minutes} минут и срабатывает один раз.\n'
        'Если вы не запрашивали восстановление, письмо можно удалить — '
        'пароль останется прежним.\n'
    )


__all__ = [
    'DeliveryResult',
    'FAILOVER_THRESHOLD',
    'failures',
    'on_failover',
    'reset_password_body',
    'send_mail',
]