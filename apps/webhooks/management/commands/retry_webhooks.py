"""Повтор неудачных доставок вебхуков.

Запускается по расписанию (cron, systemd или сервис scheduler) рядом с
отложенной публикацией: своей очереди у вебхуков нет, а держать
отдельный воркер ради трёх повторов — лишняя служба в self-hosted
установке.

    python manage.py retry_webhooks
    python manage.py retry_webhooks --loop 60

`--loop` нужен стенду и небольшим установкам, где отдельный cron не
заводят. В эксплуатации с несколькими репликами лучше внешний
планировщик: две команды, запущенные одновременно, отправят одну
доставку дважды — получатель отбросит повтор по X-Aura-Delivery, но
лишний трафик никому не нужен.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from webhooks.service import retry_failed


class Command(BaseCommand):
    help = 'Повторяет неудачные доставки вебхуков (не больше MAX_ATTEMPTS).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=50,
            help='Сколько доставок обработать за прогон (по умолчанию 50).',
        )
        parser.add_argument(
            '--loop', type=int, default=0, metavar='СЕКУНД',
            help='не завершаться, а повторять проверку каждые N секунд',
        )

    def handle(self, *args, **options):
        while True:
            sent, failed = retry_failed(limit=options['limit'])
            # Молчим, когда повторять нечего: при --loop иначе каждую
            # минуту в журнал попадала бы пустая строка.
            if sent or failed:
                self.stdout.write(
                    f'Вебхуки: доставлено {sent}, не доставлено {failed}.'
                )

            delay = max(0, int(options['loop'] or 0))
            if delay <= 0:
                return
            time.sleep(delay)
