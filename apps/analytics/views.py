"""API аналитики и публичный приём заявок.

Два разных потребителя в одном приложении. Заявки приходят с сайта
без авторизации: их отправитель — посетитель, а не участник проекта.
Аналитику читает редактор, и она подчиняется тем же правилам доступа,
что и сам проект.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response

from accounts.permissions import VIEW, can
from projects.models import Project
from publications.models import STATE_ACTIVE, Site

from .forms import (
    MAX_FORM_BYTES,
    clean_fields,
    page_from_referer,
    site_slug_from_referer,
    utm_from_referer,
)
from .models import FormSubmission, PageView, TrafficSource
from .throttling import FormRateThrottle
from .tracking import traffic_source

#: Периоды, которые понимает экран. Список фиксирован, а не «любое
#: число дней»: интерфейс предлагает три кнопки, и произвольное
#: значение означало бы, что отчёт не с чем сравнить.
PERIODS = (7, 30, 90)

#: Сколько строк отдаётся в отчёте. Полный список источников и страниц
#: бесполезен: решение принимают по первым десяти.
TOP_ROWS = 10

#: Сколько последних заявок видно в отчёте. Это лента для быстрой
#: реакции, а не CRM: выгружать все заявки через аналитику не нужно.
RECENT_SUBMISSIONS = 20


def _project(project_id: str):
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, AttributeError, TypeError):
        return None


def _site_for_submission(request, data: dict):
    """Сайт, которому принадлежит заявка: явно или по Referer."""
    raw = data.get('_site')
    slug = raw.strip().lower()[:63] if isinstance(raw, str) else ''
    if not slug:
        slug = site_slug_from_referer(request.META.get('HTTP_REFERER', ''))
    if not slug:
        return None
    return Site.objects.filter(slug=slug).first()


@api_view(['POST'])
@permission_classes([])
@throttle_classes([FormRateThrottle])
def submit_form(request):
    """Принимает заявку с формы опубликованного сайта.

    Ответ намеренно короткий: посетителю не нужно знать, куда именно
    попала заявка. Ошибки — обычный JSON, чтобы скомпилированный
    скрипт формы мог показать человеку внятное сообщение.
    """
    length = request.META.get('CONTENT_LENGTH') or ''
    if length.isdigit() and int(length) > MAX_FORM_BYTES:
        return Response(
            {'detail': 'Заявка слишком большая.'},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    data = request.data
    if not isinstance(data, dict):
        return Response(
            {'detail': 'Ожидается объект JSON.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Ловушка для роботов: скрытое поле, которого не видит человек.
    # Отвечаем как обычно, но ничего не сохраняем — иначе робот
    # получит сигнал, что его распознали.
    if data.get('_hp'):
        return Response({'ok': True}, status=status.HTTP_201_CREATED)

    site = _site_for_submission(request, data)
    if site is None:
        return Response({'detail': 'Сайт не найден.'},
                        status=status.HTTP_404_NOT_FOUND)
    if site.state != STATE_ACTIVE:
        return Response({'detail': 'Сайт отозван.'},
                        status=status.HTTP_410_GONE)

    fields = clean_fields(data)
    if not fields:
        return Response({'detail': 'Заявка пуста.'},
                        status=status.HTTP_400_BAD_REQUEST)

    referer = request.META.get('HTTP_REFERER', '')
    source = traffic_source(
        referer, request.get_host(), utm_from_referer(referer),
    )
    if source == 'internal':
        # Для заявки «внутренний переход» — бессмыслица: посетитель уже
        # на сайте, а откуда он пришёл впервые, сервер не знает. UTM в
        # адресе страницы — единственное, что можно сохранить честно.
        source = 'direct'

    FormSubmission.objects.create(
        site=site,
        page=page_from_referer(referer, site.slug),
        source=source,
        data=fields,
    )
    return Response({'ok': True}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([])
def project_analytics(request, project_id: str):
    """Сводка по опубликованному сайту проекта за выбранный период."""
    project = _project(project_id)
    if project is None or not can(request.user, project, VIEW):
        # 404, а не 403: иначе по коду ответа можно перебирать проекты.
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    raw = request.query_params.get('days', str(PERIODS[0]))
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = PERIODS[0]
    if days not in PERIODS:
        return Response(
            {'detail': f'Период должен быть одним из: {", ".join(map(str, PERIODS))}.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    site = Site.objects.filter(project=project).first()
    if site is None:
        return Response({
            'days': days,
            'site': None,
            'totals': {'views': 0, 'submissions': 0, 'conversion': 0.0},
            'series': [],
            'sources': [],
            'pages': [],
            'submissions': [],
        })

    start = timezone.localdate() - timedelta(days=days - 1)

    views_by_day = {
        row['day']: row['total']
        for row in PageView.objects
        .filter(site=site, day__gte=start)
        .values('day')
        .annotate(total=Sum('views'))
    }
    submissions_by_day = {
        row['day']: row['total']
        for row in FormSubmission.objects
        .filter(site=site, created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Count('id'))
    }

    total_views = sum(views_by_day.values())
    total_submissions = sum(submissions_by_day.values())
    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        series.append({
            'day': day.isoformat(),
            'views': views_by_day.get(day, 0),
            'submissions': submissions_by_day.get(day, 0),
        })

    def share(value: int) -> float:
        return round(value / total_views, 3) if total_views else 0.0

    sources = [
        {'source': row['source'], 'views': row['total'], 'share': share(row['total'])}
        for row in TrafficSource.objects
        .filter(site=site, day__gte=start)
        .values('source')
        .annotate(total=Sum('views'))
        .order_by('-total')[:TOP_ROWS]
    ]
    pages = [
        {'path': row['path'], 'views': row['total'], 'share': share(row['total'])}
        for row in PageView.objects
        .filter(site=site, day__gte=start)
        .values('path')
        .annotate(total=Sum('views'))
        .order_by('-total')[:TOP_ROWS]
    ]
    recent = [
        item.public_dict()
        for item in site.submissions.filter(created_at__date__gte=start)
        [:RECENT_SUBMISSIONS]
    ]

    return Response({
        'days': days,
        'site': {
            'slug': site.slug,
            'url': site.url(),
            'published': site.is_active,
            'currentVersion': (
                site.current_version.number if site.current_version else None
            ),
        },
        'totals': {
            'views': total_views,
            'submissions': total_submissions,
            # Процент, а не доля: владельцу сайта нужно «2,4%», а не
            # «0.024», и считать это в интерфейсе незачем.
            'conversion': (
                round(total_submissions / total_views * 100, 1)
                if total_views else 0.0
            ),
        },
        'series': series,
        'sources': sources,
        'pages': pages,
        'submissions': recent,
    })


__all__ = ['PERIODS', 'project_analytics', 'submit_form']
