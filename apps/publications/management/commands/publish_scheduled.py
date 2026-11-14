"""Команда планировщика: `python manage.py publish_scheduled`.

Приложение не держит собственный демон: публикация уже собрана и лежит
на диске, а включение — это переключение текущей версии. Поэтому здесь
достаточно периодической команды, которую вызывает cron, systemd timer
или сервис `scheduler` в docker-compose.

`--loop` нужен стенду и небольшим установкам, где отдельный cron не
заводят: команда сама просыпается раз в N секунд. В эксплуатации с
несколькими репликами лучше внешний планировщик: два процесса,
запущенные одновременно, не опубликуют одно задание дважды, но будут
мешать друг другу впустую.

    python manage.py publish_scheduled
    python manage.py publish_scheduled --loop 60
    python manage.py publish_scheduled --dry-run
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from publications.models import SCHEDULE_DONE
from publications.service import apply_due, due_schedules


class Command(BaseCommand):
    help = 'Публикует отложенные версии сайтов, время которых наступило'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop', type=int, default=0, metavar='СЕКУНД',
            help='не завершаться, а повторять проверку каждые N секунд',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='только показать, что готово к публикации',
        )

    def handle(self, *args, **options):
        while True:
            if options['dry_run']:
                self._show_due()
            else:
                self._apply()

            delay = max(0, int(options['loop'] or 0))
            if delay <= 0:
                return
            time.sleep(delay)

    def _show_due(self) -> None:
        due = due_schedules()
        if not due:
            self.stdout.write('Нет отложенных публикаций, готовых к выходу.')
            return
        for schedule in due:
            self.stdout.write(
                f'{schedule.site.slug}: версия {schedule.version_number}, '
                f'запланирована на '
                f'{schedule.scheduled_at:%d.%m.%Y %H:%M}'
            )

    def _apply(self) -> None:
        applied = apply_due()
        if not applied:
            return
        for schedule in applied:
            if schedule.state == SCHEDULE_DONE:
                self.stdout.write(self.style.SUCCESS(
                    f'{schedule.site.slug}: опубликована версия '
                    f'{schedule.version_number}'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'{schedule.site.slug}: версия '
                    f'{schedule.version_number} не опубликована — '
                    f'{schedule.error or "неизвестная ошибка"}'
                ))
