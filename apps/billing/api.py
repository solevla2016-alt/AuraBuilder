"""HTTP-слой биллинга: тариф, смена тарифа, что доступно."""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant import credits as ai_credits

from .plans import PLANS
from .service import (
    SCENARIO_TITLES,
    check_scenario,
    plan_for,
    published_projects,
    quota_row,
    usage_for,
)


class PlanSerializer(serializers.Serializer):
    code = serializers.CharField()
    title = serializers.CharField()
    price = serializers.IntegerField()
    max_projects = serializers.IntegerField(allow_null=True)
    max_pages = serializers.IntegerField(allow_null=True)
    max_records = serializers.IntegerField(allow_null=True)
    ai_credits = serializers.IntegerField(allow_null=True)
    own_domain = serializers.BooleanField()
    cdn_priority = serializers.BooleanField()
    onedc_integration = serializers.BooleanField()


def _plan_payload(plan) -> dict:
    return {
        'code': plan.code,
        'title': plan.title,
        'price': plan.price,
        'max_projects': plan.max_projects,
        'max_pages': plan.max_pages,
        'max_records': plan.max_records,
        'ai_credits': plan.ai_credits,
        'own_domain': plan.own_domain,
        'cdn_priority': plan.cdn_priority,
        'onedc_integration': plan.onedc_integration,
    }


class SubscriptionView(APIView):
    """Текущий тариф и перечень тарифов для выбора."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        subscription = getattr(request.user, 'subscription', None)
        plan = plan_for(request.user)
        usage = usage_for(request.user)
        available = {
            scenario: check_scenario(request.user, scenario) is None
            for scenario in range(1, 6)
        }
        return Response({
            'plan': _plan_payload(plan),
            'pending_plan': (
                subscription.pending_plan if subscription else ''
            ),
            'available': available,
            # Названия сценариев отдаются вместе с доступностью: иначе
            # интерфейс держал бы вторую копию списка, и новая функция
            # появлялась бы в API, но не на экране тарифов.
            'scenarios': [
                {
                    'code': scenario,
                    'title': SCENARIO_TITLES[scenario],
                    'available': available[scenario],
                }
                for scenario in range(1, 6)
            ],
            'plans': [_plan_payload(item) for item in PLANS.values()],
            # Использование нужно тем же ответом, что и тариф: два
            # запроса на один экран разошлись бы, если между ними
            # успели создать проект, и полоса квоты показала бы чужое
            # число.
            'usage': {
                'projects': quota_row(usage['projects'], plan.max_projects),
                'pages': quota_row(usage['pages'], plan.max_pages),
                'records': quota_row(usage['records'], plan.max_records),
                # Кредиты помощника входят в ту же шкалу, поэтому
                # остаток приходит одним ответом с тарифом: иначе
                # кабинет показывал бы квоты без расхода на ИИ.
                'ai': quota_row(
                    ai_credits.used_credits(request.user),
                    plan.ai_credits,
                ),
            },
            'publications': {'published': published_projects(request.user)},
            # Фронт скрывает тарифы в self-hosted. Флаг отдаётся, а не
            # угадывается по коду тарифа: Business там выдаётся всем, и
            # «раз тариф Business — значит облако» было бы неверно.
            'billing_enabled': settings.BILLING_ENABLED,
        })


class ChangePlanView(APIView):
    """Смена тарифа: действует сразу, понижение — в течение суток."""

    permission_classes = [IsAuthenticated]

    class Input(serializers.Serializer):
        plan = serializers.ChoiceField(choices=list(PLANS))

    def post(self, request):
        payload = self.Input(data=request.data)
        payload.is_valid(raise_exception=True)
        code = payload.validated_data['plan']

        # В self-hosted шкалы нет: смена тарифа вернула бы владельцу
        # установки Free и лимиты, которых на его сервере быть не
        # должно. Отказ явный, а не молчаливое игнорирование.
        if not settings.BILLING_ENABLED:
            return Response(
                {
                    'detail': 'На этом сервере тарифы отключены: '
                              'все возможности доступны без подписки.',
                    'reason': 'billing_disabled',
                },
                status=400,
            )

        from .models import Subscription  # локальный импорт против цикла
        from django.utils import timezone

        subscription, _ = Subscription.objects.get_or_create(user=request.user)
        subscription.plan = code
        subscription.pending_plan = ''
        subscription.pending_since = None
        subscription.active = True
        subscription.save()
        return Response({
            'plan': _plan_payload(plan_for(request.user)),
            'effective': 'now',
            'note': 'Понижение тарифа вступит в силу в течение суток; '
                    'при превышении лимитов публикация новых страниц '
                    'будет заблокирована, действующие страницы '
                    'продолжат работать.',
            'since': timezone.now().isoformat(),
        })


__all__ = ['ChangePlanView', 'PlanSerializer', 'SubscriptionView']