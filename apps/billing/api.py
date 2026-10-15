"""HTTP-слой биллинга: тариф, смена тарифа, что доступно."""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .plans import PLANS
from .service import check_scenario, plan_for


class PlanSerializer(serializers.Serializer):
    code = serializers.CharField()
    title = serializers.CharField()
    price = serializers.IntegerField()
    max_projects = serializers.IntegerField(allow_null=True)
    max_pages = serializers.IntegerField(allow_null=True)
    max_records = serializers.IntegerField(allow_null=True)
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
            'plans': [_plan_payload(item) for item in PLANS.values()],
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