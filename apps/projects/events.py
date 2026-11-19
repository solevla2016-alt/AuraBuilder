"""События проекта и их доставка.

Журнал событий — это короткая лента «что произошло с сайтом»: собрали
архив, опубликовали версию, выложили на хостинг. Он нужен интерфейсу и
уведомлениям, но не заменяет аудит: аудит отвечает, кто что сделал, а
событие — что получилось.

Запись события не имеет права ломать основную операцию. Публикация уже
произошла, когда мы пишем строку в журнал; если журнал недоступен,
человек всё равно должен увидеть опубликованный сайт. Поэтому ошибки
записи и отправки проглатываются с записью в лог.
"""

from __future__ import annotations

import logging

from .models import ProjectEvent

logger = logging.getLogger(__name__)

#: Сколько событий хранится на проект. Лента нужна для последних
#: действий, а не как архив: без границы таблица росла бы с каждой
#: выгрузкой архива.
KEEP_EVENTS = 200


def record(project, kind: str, message: str,
           status: str = ProjectEvent.STATUS_INFO,
           actor=None) -> ProjectEvent | None:
    """Записывает событие и, если получится, отправляет его в Telegram."""

    try:
        event = ProjectEvent.objects.create(
            project=project,
            kind=kind,
            status=status,
            # Длина поля ограничена: длинный текст ошибки обрезается, а
            # не превращает запись журнала в отказ всей операции.
            message=str(message)[:300],
            actor=actor,
        )
        _prune(project)
    except Exception:  # noqa: BLE001 — журнал не должен ломать действие
        logger.exception('не удалось записать событие проекта %s', project.pk)
        return None

    _notify(event)
    return event


def _prune(project) -> None:
    stale = list(
        ProjectEvent.objects.filter(project=project)
        .order_by('-created_at')
        .values_list('id', flat=True)[KEEP_EVENTS:]
    )
    if stale:
        ProjectEvent.objects.filter(id__in=stale).delete()


def _notify(event: ProjectEvent) -> None:
    # Импорт внутри функции: telegram зависит от projects, и обратный
    # импорт на уровне модуля замкнул бы приложение на себя.
    try:
        from telegram.notifications import notify_event

        notify_event(event)
    except Exception:  # noqa: BLE001 — доставка не входит в операцию
        logger.exception('событие %s не доставлено в Telegram', event.pk)

    # Вебхуки — тоже доставка, а не часть операции: недоступный приёмник
    # оставляет запись в журнале доставок, но не отменяет публикацию.
    try:
        from webhooks.service import dispatch

        dispatch(event)
    except Exception:  # noqa: BLE001
        logger.exception('событие %s не разослано по вебхукам', event.pk)


def recent(project, limit: int = 20):
    return ProjectEvent.objects.filter(project=project).select_related(
        'actor',
    )[:limit]


__all__ = ['KEEP_EVENTS', 'record', 'recent']
