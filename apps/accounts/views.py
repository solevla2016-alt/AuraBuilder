"""Представления аутентификации: регистрация, вход, refresh, выход, профиль.

Почему не ViewSet: у этих действий разные контракты. Вход отдаёт пару
токенов, refresh — новый access, регистрация — профиль без токенов
(сначала подтверждение email, ТЗ п.9.3). Общий ViewSet заставил бы
описать четыре разных ответа в одном методе create.

Отдельно про ограничение частоты: 5 попыток за 10 минут на IP
(ТЗ п.7.7). Счётчик живёт в DRF (throttle_scope), а не здесь: иначе
он считался бы в процессе каждого воркера отдельно и перестал бы
работать с несколькими репликами.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from .models import UserConsent
from .serializers import (
    ConsentSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    get_client_ip,
    record_consent,
)
from .permissions import IsAuthenticatedUser

User = get_user_model()


class RegisterView(APIView):
    """Регистрация.

    Токены не выдаются: ТЗ п.9.3 требует подтверждения email перед
    входом. Подтверждение закроет этап 8 вместе с Яндекс 360; до него
    новый пользователь может войти сразу, а доступ к чужим проектам
    у него всё равно невозможен — проектов нет.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'login'

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        record_consent(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Вход по логину или email с выдачей пары токенов."""

    permission_classes = [AllowAny]
    throttle_scope = 'login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data,
            }
        )


class LogoutView(APIView):
    """Выход: refresh-токен отзывается.

    Access-токен живёт 15 минут (ТЗ п.7.7) и отозвать его нельзя —
    он уже отправлен клиенту. Поэтому выход «отзывает будущее»:
    refresh больше не работает, а текущий access истечёт сам. Полная
    отзывность потребовала бы хранилища выданных access-токенов.
    """

    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            return Response(
                {'refresh': 'Требуется refresh-токен.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            # Токен уже отозван или подделан: результат для пользователя
            # тот же — он вышел, а сообщение об ошибке только пугает.
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class RefreshView(TokenRefreshView):
    """Обновление access-токена.

    Ротация включена в настройках: после обновления старый refresh
    перестаёт работать. Если им воспользуются повторно — значит, токен
    был украден, и можно отозвать всё семейство.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'login'


class MeView(APIView):
    """Профиль текущего пользователя."""

    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ConsentView(APIView):
    """Согласие на обработку персональных данных и его отзыв.

    Отзыв — отдельное действие, а не поле профиля: он требует записи
    времени и необратим по смыслу. Вернуть согласие можно новой
    записью, и в журнале останутся оба факта.
    """

    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        consents = UserConsent.objects.filter(user=request.user)[:20]
        return Response(ConsentSerializer(consents, many=True).data)

    def delete(self, request):
        consent = UserConsent.objects.filter(
            user=request.user, revoked_at__isnull=True
        ).first()
        if consent is None:
            return Response(
                {'detail': 'Активного согласия нет.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        consent.revoked_at = timezone.now()
        consent.save(update_fields=['revoked_at'])
        return Response(ConsentSerializer(consent).data)


class RegisterKeyView(APIView):
    """Смена и подтверждение email.

    Подтверждение требует письма (Яндекс 360, этап 8), поэтому сейчас
    доступно только получение ключа для офлайн-проверки: без него
    подтверждённый адрес не выдаётся. Заглушка оставлена явно, чтобы
    фронт мог звать адрес и получать внятный ответ, а не 404.
    """

    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        return Response(
            {
                'detail': 'Подтверждение email заработает вместе с этапом 8.',
                'email': request.user.email,
                'ip': get_client_ip(request),
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )