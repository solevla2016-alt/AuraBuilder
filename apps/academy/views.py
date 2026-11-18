"""API Академии: уроки и прогресс пользователя.

Право одно — вход в аккаунт. Уроки не содержат чужих данных и не
зависят от проекта: их читает любой участник, в том числе Viewer,
которому полезно понять, как устроен редактор, прежде чем оставлять
замечания.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedUser

from .content import LESSONS, LESSONS_BY_ID, TRACKS, lesson_public
from .models import LessonProgress


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def lesson_list(request):
    """Уроки по разделам с отметками текущего пользователя."""

    done = dict(
        LessonProgress.objects.filter(user=request.user)
        .values_list('lesson_id', 'completed_at')
    )
    tracks = []
    for track_id, track_title in TRACKS:
        lessons = [
            lesson_public(lesson, done.get(lesson['id']))
            for lesson in LESSONS
            if lesson['track'] == track_id
        ]
        tracks.append({
            'id': track_id,
            'title': track_title,
            'lessons': lessons,
            'completed': sum(1 for lesson in lessons if lesson['completed']),
            'total': len(lessons),
        })

    return Response({
        'tracks': tracks,
        'completed': sum(1 for lesson in LESSONS if lesson['id'] in done),
        'total': len(LESSONS),
    })


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def lesson_progress(request, lesson_id: str):
    """Отметить урок пройденным или снять отметку."""

    if lesson_id not in LESSONS_BY_ID:
        return Response(
            {'detail': 'урок не найден'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == 'DELETE':
        LessonProgress.objects.filter(
            user=request.user, lesson_id=lesson_id,
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    _, created = LessonProgress.objects.get_or_create(
        user=request.user, lesson_id=lesson_id,
    )
    # Повторная отметка не ошибка: двойной клик и обновлённая вкладка
    # не должны показывать «уже пройдено» как сбой.
    return Response(
        {'lessonId': lesson_id, 'completed': True},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )
