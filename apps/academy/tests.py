"""Академия: уроки и прогресс пользователя.

Проверяется поведение, а не наличие уроков: чужой прогресс не виден,
отметка идемпотентна, снятие отметки освобождает урок, а неизвестный id
не создаёт запись в базе.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from academy.content import LESSONS, TRACKS
from academy.models import LessonProgress

User = get_user_model()


class AcademyApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'student', 'student@example.com', 'student-pass-123',
        )
        self.other = User.objects.create_user(
            'other', 'other@example.com', 'other-pass-123',
        )
        self.url = '/api/academy/'
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token("student", "student-pass-123")}',
        )

    def _token(self, login: str, password: str) -> str:
        response = self.client.post(
            '/api/auth/login/', {'login': login, 'password': password},
            format='json',
        )
        return response.data['access']

    def _progress_url(self, lesson_id: str) -> str:
        return f'/api/academy/{lesson_id}/complete/'

    def test_list_requires_login(self):
        anonymous = self.client_class()
        response = anonymous.get(self.url)
        self.assertIn(response.status_code,
                      (status.HTTP_401_UNAUTHORIZED,
                       status.HTTP_403_FORBIDDEN))

    def test_list_returns_tracks_and_all_lessons(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['total'], len(LESSONS))
        self.assertEqual(response.data['completed'], 0)
        self.assertEqual(
            [track['id'] for track in response.data['tracks']],
            [track_id for track_id, _ in TRACKS],
        )
        returned = [
            lesson['id']
            for track in response.data['tracks']
            for lesson in track['lessons']
        ]
        self.assertEqual(returned, [lesson['id'] for lesson in LESSONS])
        for track in response.data['tracks']:
            self.assertEqual(track['total'], len(track['lessons']))
            self.assertEqual(track['completed'], 0)

    def test_complete_and_uncomplete(self):
        first = LESSONS[0]['id']
        completed = self.client.post(self._progress_url(first), {}, format='json')
        self.assertEqual(completed.status_code, status.HTTP_201_CREATED,
                         completed.data)
        self.assertEqual(
            LessonProgress.objects.filter(user=self.user, lesson_id=first).count(),
            1,
        )

        listing = self.client.get(self.url)
        self.assertEqual(listing.data['completed'], 1)
        lesson = next(
            item
            for track in listing.data['tracks']
            for item in track['lessons']
            if item['id'] == first
        )
        self.assertTrue(lesson['completed'])
        self.assertIsNotNone(lesson['completedAt'])

        removed = self.client.delete(self._progress_url(first))
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            LessonProgress.objects.filter(user=self.user, lesson_id=first).exists(),
        )

    def test_repeat_complete_is_idempotent(self):
        lesson = LESSONS[0]['id']
        first = self.client.post(self._progress_url(lesson), {}, format='json')
        second = self.client.post(self._progress_url(lesson), {}, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(
            LessonProgress.objects.filter(user=self.user, lesson_id=lesson).count(),
            1,
        )

    def test_unknown_lesson_is_404(self):
        response = self.client.post(
            self._progress_url('no-such-lesson'), {}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(LessonProgress.objects.count(), 0)

    def test_progress_is_per_user(self):
        self.client.post(self._progress_url(LESSONS[0]['id']), {}, format='json')

        other = self.client_class()
        other.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self._token("other", "other-pass-123")}',
        )
        listing = other.get(self.url)
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data['completed'], 0)
        self.assertTrue(
            all(
                not lesson['completed']
                for track in listing.data['tracks']
                for lesson in track['lessons']
            ),
        )

    def test_lesson_content_is_addressable(self):
        """id уникальны и у каждого трека есть уроки: иначе прогресс
        считался бы по несуществующим разделам."""
        ids = [lesson['id'] for lesson in LESSONS]
        self.assertEqual(len(ids), len(set(ids)))
        tracks = {track_id for track_id, _ in TRACKS}
        self.assertEqual({lesson['track'] for lesson in LESSONS}, tracks)
