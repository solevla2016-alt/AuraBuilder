"""Команда деплоя: `python manage.py deploy_site`.

Нужна для разовых запусков с сервера и для приёмки: деплой по API
идёт через ту же функцию `deploying.service.deploy`, поэтому команда
не может разойтись с тем, что делает платформа.

    python manage.py deploy_site <uuid-проекта> --profile <uuid-хостинга>
    python manage.py deploy_site <uuid> --profile <uuid> --no-verify
    python manage.py deploy_site <uuid> --profile <uuid> --rotate-key
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from projects.models import DocumentVersion, Project

from deploying.models import HostingProfile
from deploying.service import deploy


class Command(BaseCommand):
    help = 'Выкладывает проект на хостинг по профилю доступа (ТЗ п.16.5)'

    def add_arguments(self, parser):
        parser.add_argument('project', help='идентификатор проекта (uuid)')
        parser.add_argument('--profile', required=True, help='профиль хостинга')
        parser.add_argument(
            '--version', type=int, default=None,
            help='номер версии; по умолчанию последняя',
        )
        parser.add_argument(
            '--no-verify', action='store_true',
            help='не проверять сайт по HTTP после загрузки',
        )
        parser.add_argument(
            '--rotate-key', action='store_true',
            help='выпустить новый siteKey: cookie покупателей перестанут '
                 'подходить, корзины сбросятся',
        )

    def handle(self, *args, **options):
        try:
            project = Project.objects.get(id=options['project'])
        except (Project.DoesNotExist, ValueError) as exc:
            raise CommandError(f'проект не найден: {options["project"]}') from exc

        profile = self._find_profile(project, options['profile'])

        version = self._pick_version(project, options['version'])

        self.stdout.write(f'Проект: {project.name}, версия {version.number}')
        self.stdout.write(f'Хостинг: {profile.name} ({profile.kind})')

        result = deploy(
            project,
            version,
            profile,
            verify=not options['no_verify'],
            rotate_key=bool(options['rotate_key']),
        )

        self.stdout.write(
            f'Загружено файлов: {result.files_uploaded}, '
            f'удалено устаревших: {result.files_removed}, '
            f'файлов рантайма: {result.runtime_files}'
        )
        for check in result.checks:
            mark = 'ок' if check['ok'] else '!!'
            self.stdout.write(f'  {mark} {check["name"]}: {check["detail"]}')
        for warning in result.warnings:
            self.stdout.write(f'  !  {warning}')

        if not result.ok:
            raise CommandError('деплой завершился с ошибкой')
        self.stdout.write(self.style.SUCCESS('деплой завершён'))

    def _find_profile(self, project, reference: str) -> HostingProfile:
        """Профиль ищется по id, имени или хосту — и только своего
        владельца: чужой профиль хостинга выдавал бы доступ к чужому
        серверу."""
        lookup = Q(id=reference) if _looks_like_uuid(reference) else Q(name=reference)
        found = HostingProfile.objects.filter(
            lookup, owner=project.owner
        ).first()
        if found is None:
            found = HostingProfile.objects.filter(
                owner=project.owner, host=reference
            ).first()
        if found is None:
            raise CommandError(
                f'профиль хостинга не найден среди ваших: {reference}'
            )
        return found

    def _pick_version(self, project, number: int | None) -> DocumentVersion:
        versions = project.versions.all()
        if number is not None:
            version = versions.filter(number=number).first()
            if version is None:
                raise CommandError(f'версия {number} не найдена')
            return version
        version = versions.order_by('-number').first()
        if version is None:
            raise CommandError('у проекта нет зафиксированных версий')
        return version


def _looks_like_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
