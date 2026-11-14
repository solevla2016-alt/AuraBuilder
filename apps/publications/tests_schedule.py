"""Отложенная публикация: собрать сейчас, включить в заданное время.

Главное, что здесь проверяется: до назначенного времени посетитель
видит старую версию, а после — новую, даже если планировщик проснулся
с опозданием. Ошибка одного задания не должна отменять остальные.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Membership
from accounts.permissions import Role
from projects.models import Project, ProjectEvent
from projects.versions import snapshot

from publications.models import (
    SCHEDULE_CANCELLED,
    SCHEDULE_DONE,
    SCHEDULE_FAILED,
    SCHEDULE_PENDING,
    ScheduledPublication,
    Site,
)
from publications.service import (
    KEEP_VERSIONS,
    apply_due,
    cancel_schedule,
    due_schedules,
    publish,
    schedule_publication,
    status_payload,
    withdraw,
)


def block(text: str = 'Заголовок') -> dict:
    return {
        'id': 'b1', 'module': 'text.heading', 'x': 0, 'y': 0,
        'width': 600, 'height': 200, 'label': 'Блок',
        'props': {'text': text},
    }


@override_settings(LOGIN_ATTEMPT_LIMIT=1000)
class ScheduleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(
            PUBLISH_ROOT=Path(self.tmp.name), PUBLICATION_BASE_URL=''
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

        User = get_user_model()
        self.user = User.objects.create_user('owner', password='pass-owner')
        self.project = Project.objects.create(
            owner=self.user, name='Цветы', tree={'width': 1200, 'blocks': []}
        )
        self.project.tree = {'width': 1200, 'blocks': [block()]}
        self.project.version += 1
        self.project.save(update_fields=['tree', 'version'])
        self.version = snapshot(self.project, self.project.tree,
                                author=self.user, label='v1')

    def next_version(self, text: str) -> None:
        self.project.version += 1
        self.project.tree = {'width': 1200, 'blocks': [block(text)]}
        self.project.save(update_fields=['tree', 'version'])
        self.version = snapshot(self.project, self.project.tree,
                                author=self.user, label=f'v{self.project.version}')

    def client_for(self, user=None, password='pass-owner'):
        client = APIClient()
        response = client.post(
            '/api/auth/login/',
            {'login': (user or self.user).username, 'password': password},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}'
        )
        return client

    def at(self, minutes: int) -> datetime:
        return timezone.now() + timedelta(minutes=minutes)

    # --- сборка и включение -------------------------------------------

    def test_version_is_built_at_planning_time(self):
        """Если собирать в момент выхода, ошибка сборки всплывёт тогда,
        когда сайт уже должен был обновиться."""
        schedule, _warnings = schedule_publication(
            self.project, self.version, self.at(30)
        )
        site = Site.objects.get()
        version = site.versions.get(number=self.version.number)
        self.assertTrue((version.directory / 'index.html').is_file())
        self.assertIsNone(site.current_version)
        self.assertEqual(schedule.state, SCHEDULE_PENDING)

    def test_nothing_happens_before_the_time(self):
        schedule_publication(self.project, self.version, self.at(30))
        applied = apply_due(now=self.at(10))
        self.assertEqual(applied, [])
        self.assertIsNone(Site.objects.get().current_version)

    def test_version_is_switched_when_time_comes(self):
        when = self.at(30)
        schedule_publication(self.project, self.version, when)
        applied = apply_due(now=when + timedelta(minutes=1))

        self.assertEqual(len(applied), 1)
        site = Site.objects.get()
        self.assertEqual(site.current_version.number, self.version.number)
        self.assertTrue(site.is_active)
        self.assertEqual(applied[0].state, SCHEDULE_DONE)
        self.assertIsNotNone(applied[0].finished_at)

    def test_published_at_is_scheduled_time_not_wakeup(self):
        """Задержка таймера на минуту не должна сдвигать дату выхода
        версии в отчёте."""
        when = self.at(30)
        schedule_publication(self.project, self.version, when)
        apply_due(now=when + timedelta(minutes=7))

        site = Site.objects.get()
        self.assertEqual(site.published_at, when)

    def test_site_becomes_available_after_the_time(self):
        when = self.at(30)
        scheduled = schedule_publication(self.project, self.version, when)[0]
        self.assertEqual(
            self.client.get(f'/sites/{scheduled.site.slug}/').status_code, 404
        )
        apply_due(now=when)
        response = self.client.get(f'/sites/{scheduled.site.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Заголовок', response.content.decode('utf-8'))

    def test_first_publication_can_be_scheduled(self):
        """Планирование первой публикации не должно требовать «сначала
        опубликовать руками»."""
        when = self.at(5)
        schedule, _warnings = schedule_publication(
            self.project, self.version, when
        )
        self.assertEqual(schedule.site.slug, 'site')
        apply_due(now=when)
        site = Site.objects.get()
        self.assertTrue(site.is_active)
        self.assertEqual(site.current_version.number, self.version.number)

    def test_several_schedules_switch_in_time_order(self):
        when = self.at(10)
        first = schedule_publication(self.project, self.version, when)[0]
        self.next_version('Вторая')
        second = schedule_publication(
            self.project, self.version, when + timedelta(minutes=5)
        )[0]

        applied = apply_due(now=when + timedelta(minutes=10))

        self.assertEqual([item.id for item in applied], [first.id, second.id])
        site = Site.objects.get()
        self.assertEqual(site.current_version.number, second.version_number)

    def test_one_failure_does_not_stop_the_queue(self):
        """Сбой одного задания не должен задерживать следующее."""
        when = self.at(10)
        broken = schedule_publication(self.project, self.version, when)[0]
        shutil.rmtree(
            broken.site.versions.get(number=broken.version_number).directory
        )
        self.next_version('Живая')
        alive = schedule_publication(
            self.project, self.version, when + timedelta(minutes=1)
        )[0]

        applied = apply_due(now=when + timedelta(minutes=5))

        self.assertEqual(
            {item.state for item in applied}, {SCHEDULE_FAILED, SCHEDULE_DONE}
        )
        self.assertEqual(Site.objects.get().current_version.number,
                         alive.version_number)

    def test_missing_files_fail_loudly(self):
        """Задание должно остаться видимым и объяснить, что случилось:
        «ничего не произошло» — худший ответ."""
        when = self.at(10)
        schedule = schedule_publication(self.project, self.version, when)[0]
        version = schedule.site.versions.get(number=schedule.version_number)
        shutil.rmtree(version.directory)

        applied = apply_due(now=when)

        self.assertEqual(applied[0].state, SCHEDULE_FAILED)
        self.assertIn('удалена', applied[0].error)
        event = ProjectEvent.objects.get(kind=ProjectEvent.KIND_SCHEDULE)
        self.assertEqual(event.status, ProjectEvent.STATUS_FAILED)

    def test_completed_schedule_records_event(self):
        when = self.at(10)
        schedule_publication(self.project, self.version, when)
        apply_due(now=when)
        event = ProjectEvent.objects.get(kind=ProjectEvent.KIND_SCHEDULE)
        self.assertEqual(event.status, ProjectEvent.STATUS_OK)
        self.assertIn(f'версия {self.version.number}', event.message)

    # --- отмена и отзыв -----------------------------------------------

    def test_cancel_stops_the_publication(self):
        when = self.at(10)
        schedule = schedule_publication(self.project, self.version, when)[0]
        self.assertTrue(cancel_schedule(schedule))

        apply_due(now=when + timedelta(minutes=1))

        self.assertEqual(Site.objects.get().current_version, None)
        schedule.refresh_from_db()
        self.assertEqual(schedule.state, SCHEDULE_CANCELLED)

    def test_cancel_of_completed_returns_false(self):
        when = self.at(10)
        schedule = schedule_publication(self.project, self.version, when)[0]
        apply_due(now=when)
        schedule.refresh_from_db()
        self.assertFalse(cancel_schedule(schedule))

    def test_withdraw_cancels_pending_publication(self):
        """Иначе убранный владельцем сайт вернулся бы сам, и человек
        узнал бы об этом от посетителей."""
        schedule = schedule_publication(self.project, self.version, self.at(10))[0]
        withdraw(schedule.site)

        schedule.refresh_from_db()
        self.assertEqual(schedule.state, SCHEDULE_CANCELLED)
        self.assertEqual(due_schedules(now=self.at(60)).count(), 0)

    def test_prune_keeps_versions_waiting_for_their_time(self):
        """Чистка старых версий не должна удалять ту, которую ждёт
        отложенное задание: иначе оно провалится по вине платформы."""
        when = self.at(30)
        schedule = schedule_publication(self.project, self.version, when)[0]
        for index in range(KEEP_VERSIONS + 2):
            self.next_version(f'Версия {index}')
            publish(self.project, self.version)

        waiting = schedule.site.versions.get(number=schedule.version_number)
        self.assertTrue((waiting.directory / 'index.html').is_file())

        apply_due(now=when)
        self.assertEqual(Site.objects.get().current_version.number,
                         schedule.version_number)

    # --- API -----------------------------------------------------------

    def test_api_schedules_and_lists(self):
        client = self.client_for()
        at = self.at(60).isoformat()
        response = client.post(
            f'/api/projects/{self.project.id}/site/schedule/',
            {'at': at}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['schedule']['version'],
                         self.version.number)
        self.assertEqual(len(response.data['scheduled']), 1)

        listing = client.get(f'/api/projects/{self.project.id}/site/schedule/')
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(len(listing.data['scheduled']), 1)

    def test_api_refuses_past_time(self):
        client = self.client_for()
        response = client.post(
            f'/api/projects/{self.project.id}/site/schedule/',
            {'at': self.at(-5).isoformat()}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_api_refuses_broken_time(self):
        client = self.client_for()
        response = client.post(
            f'/api/projects/{self.project.id}/site/schedule/',
            {'at': 'завтра'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_api_refuses_unknown_version(self):
        client = self.client_for()
        response = client.post(
            f'/api/projects/{self.project.id}/site/schedule/',
            {'at': self.at(30).isoformat(), 'version': 999}, format='json',
        )
        self.assertEqual(response.status_code, 404, response.data)

    def test_api_without_versions_is_409(self):
        client = self.client_for()
        self.project.versions.all().delete()
        response = client.post(
            f'/api/projects/{self.project.id}/site/schedule/',
            {'at': self.at(30).isoformat()}, format='json',
        )
        self.assertEqual(response.status_code, 409, response.data)

    def test_api_requires_publish_right(self):
        """Планировать может тот, кто публикует: задание меняет то, что
        увидит посетитель."""
        viewer = get_user_model().objects.create_user(
            'viewer', password='pass-v'
        )
        Membership.objects.create(
            project=self.project, user=viewer, role=Role.VIEWER,
        )
        client = self.client_for(viewer, 'pass-v')
        response = client.post(
            f'/api/projects/{self.project.id}/site/schedule/',
            {'at': self.at(30).isoformat()}, format='json',
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_api_cancels(self):
        client = self.client_for()
        created = client.post(
            f'/api/projects/{self.project.id}/site/schedule/',
            {'at': self.at(30).isoformat()}, format='json',
        )
        schedule_id = created.data['schedule']['id']
        response = client.delete(
            f'/api/projects/{self.project.id}/site/schedule/{schedule_id}/'
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['scheduled'], [])

    def test_api_cancel_of_unknown_is_404(self):
        client = self.client_for()
        response = client.delete(
            f'/api/projects/{self.project.id}/site/schedule/{uuid.uuid4()}/'
        )
        self.assertEqual(response.status_code, 404, response.data)

    def test_api_cancel_of_broken_id_is_404(self):
        client = self.client_for()
        response = client.delete(
            f'/api/projects/{self.project.id}/site/schedule/не-uuid/'
        )
        self.assertEqual(response.status_code, 404, response.data)

    def test_status_payload_shows_pending(self):
        schedule = schedule_publication(self.project, self.version, self.at(30))[0]
        payload = status_payload(schedule.site)
        self.assertEqual(len(payload['scheduled']), 1)
        self.assertEqual(payload['scheduled'][0]['state'], SCHEDULE_PENDING)

    # --- команда планировщика -----------------------------------------

    def test_command_does_nothing_while_nothing_is_due(self):
        schedule_publication(self.project, self.version, self.at(30))
        out = io.StringIO()
        call_command('publish_scheduled', stdout=out)
        self.assertIsNone(Site.objects.get().current_version)

    def test_command_publishes_due_version(self):
        scheduled = schedule_publication(
            self.project, self.version, self.at(-1)
        )[0]
        out = io.StringIO()
        call_command('publish_scheduled', stdout=out)
        self.assertIn(scheduled.site.slug, out.getvalue())
        self.assertEqual(Site.objects.get().current_version.number,
                         scheduled.version_number)

    def test_command_dry_run_changes_nothing(self):
        schedule_publication(self.project, self.version, self.at(-1))
        out = io.StringIO()
        call_command('publish_scheduled', '--dry-run', stdout=out)
        self.assertIn('site', out.getvalue())
        self.assertIsNone(Site.objects.get().current_version)
        self.assertTrue(
            ScheduledPublication.objects.filter(state=SCHEDULE_PENDING).exists()
        )
