"""Восстановление пароля и удаление аккаунта (ТЗ п.9.1, п.13.1).

Два действия, которые нужны человеку, когда пароль утерян или когда
он хочет уйти с платформы. Объединяет их одно: обе операции необратимы
или почти необратимы, и обе должны быть защищены от чужих рук.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .emails import reset_password_body, send_mail
from .models import PasswordReset
from .permissions import IsAuthenticatedUser
from .serializers import audit_account, get_client_ip

logger = logging.getLogger(__name__)

User = get_user_model()


def _hash_key(key: str) -> str:
    """Хэш ключа из письма.

    В таблице лежит только хэш: копия базы не должна позволять войти
    под пользователем. Ключ — случайная строка, поэтому растяжения
    пароля здесь не нужно: перебор по сети бессмысленен.
    """
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _reset_link(key: str) -> str:
    base = (getattr(settings, 'PLATFORM_BASE_URL', '') or '').rstrip('/')
    return f'{base}/reset-password/?token={key}'


class PasswordResetRequestSerializer(serializers.Serializer):
    """Запрос ссылки восстановления."""

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Новый пароль по ключу из письма."""

    token = serializers.CharField(max_length=128)
    password = serializers.CharField(
        write_only=True, min_length=12, trim_whitespace=False,
    )


def _validate_password(password: str) -> str | None:
    """Проверяет пароль теми же правилами, что и регистрация."""
    from django.contrib.auth.password_validation import validate_password

    try:
        validate_password(password)
    except Exception as e:  # noqa: BLE001 — DjangoException с перечнем правил
        return '; '.join(getattr(e, 'messages', [str(e)]))
    return None


class PasswordResetRequestView(APIView):
    """Высылает письмо со ссылкой восстановления.

    Ответ одинаков при любом адресе — есть такой аккаунт или нет.
    Разный ответ превращал бы форму восстановления в способ проверить,
    зарегистрирован ли адрес, а это ровно то, что такие формы чаще
    всего и выдают.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'login'

    #: Ответ не содержит адреса и ничего о наличии аккаунта.
    ANSWER = {'detail': 'Если такой адрес зарегистрирован, письмо с '
                        'ссылкой для восстановления уже отправлено.'}

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].lower()

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            logger.info('восстановление пароля для неизвестного адреса')
            return Response(self.ANSWER)

        # Прежние ключи гасятся: иначе письмо, перехваченное год назад,
        # продолжало бы работать после нескольких новых запросов.
        PasswordReset.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now(),
        )

        key = secrets.token_urlsafe(32)
        PasswordReset.objects.create(
            user=user,
            key_hash=_hash_key(key),
            requested_ip=get_client_ip(request),
            expires_at=timezone.now() + timezone.timedelta(
                minutes=PasswordReset.TTL_MINUTES,
            ),
        )

        result = send_mail(
            'AuraBuilder: восстановление пароля',
            reset_password_body(_reset_link(key), PasswordReset.TTL_MINUTES),
            [user.email],
        )
        if not result:
            # Письмо не ушло — это видно в журнале, но не пользователю:
            # ответ остаётся тем же, иначе он стал бы проверкой адреса.
            logger.error('восстановление пароля %s: письмо не отправлено (%s)',
                         user.email, result.error)

        audit_account('password.reset.requested', user, request)
        return Response(self.ANSWER)


class PasswordResetConfirmView(APIView):
    """Задаёт новый пароль по ключу из письма."""

    permission_classes = [AllowAny]
    throttle_scope = 'login'

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = serializer.validated_data['token']

        reset = PasswordReset.objects.filter(
            key_hash=_hash_key(key),
        ).select_related('user').first()
        if reset is None:
            return Response({'detail': 'Ссылка недействительна.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not reset.usable:
            # Разные сообщения для истёкшего и использованного ключа:
            # оба случая бесполезны для подбора, а различать их полезно
            # тому, кто действительно восстанавливает пароль.
            reason = ('Срок действия ссылки истёк.' if reset.expired
                      else 'Ссылка уже использована.')
            return Response({'detail': reason},
                            status=status.HTTP_400_BAD_REQUEST)

        problem = _validate_password(serializer.validated_data['password'])
        if problem:
            return Response({'detail': problem},
                            status=status.HTTP_400_BAD_REQUEST)

        user = reset.user
        user.set_password(serializer.validated_data['password'])
        user.save(update_fields=['password'])
        reset.used_at = timezone.now()
        reset.save(update_fields=['used_at'])

        # Старые сессии закрываются: пароль меняли не для того, чтобы
        # оставить входы того, кто был им до смены.
        _blackout(user)
        audit_account('password.reset.completed', user, request)

        refresh = RefreshToken.for_user(user)
        return Response({
            'detail': 'Пароль обновлён.',
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })


def _blackout(user) -> None:
    """Отзывает выданные пользователю токены."""
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
    except ImportError:  # pragma: no cover - blacklist не подключён
        return
    try:
        for token in OutstandingToken.objects.filter(user=user):
            # Запись в blacklist создаётся напрямую: пересобирать
            # токен ради его отзыва незачем, а сам токен нужен только
            # для ссылки.
            BlacklistedToken.objects.get_or_create(token=token)
    except Exception as e:  # noqa: BLE001 — отзыв не должен ломать смену
        logger.warning('не удалось отозвать токены %s: %s', user, e)


def _has_members(project) -> bool:
    """Есть ли у проекта соавторы.

    Участники, кроме владельца, и есть соавторы: работа в проекте
    принадлежит не только тому, кто его завёл.
    """
    from accounts.models import Membership

    return Membership.objects.filter(
        project=project,
    ).exclude(user=project.owner).exists()


class AccountDeleteSerializer(serializers.Serializer):
    """Подтверждение удаления паролем."""

    password = serializers.CharField(write_only=True, trim_whitespace=False)
    #: Что удалится — показываем заранее, а не после.
    confirm = serializers.BooleanField()

    #: Имена полей приходят в camelCase, как у всего API платформы.
    def to_internal_value(self, data):
        if isinstance(data, dict) and 'withProjects' in data:
            data = dict(data)
            data['with_projects'] = data.pop('withProjects')
        return super().to_internal_value(data)
    #: Отдельное подтверждение на проекты: снести чужую работу одной
    #: кнопкой нельзя, а молча оставить проекты без владельца — тоже.
    #: Имя в JSON — camelCase, как у остального API платформы.
    with_projects = serializers.BooleanField(required=False, default=False)


class AccountDeleteView(APIView):
    """Удаление аккаунта и всех его данных (ТЗ п.13.1).

    Требует пароль: удаление необратимо, и одна ошибка нажатия не
    должна стоить человеку работы.

    Проекты удаляются вместе с аккаунтом, но только если подтверждено
    отдельным флагом. Если у проекта есть соавторы, удалить его
    нельзя: работа принадлежит не только владельцу, и платформа
    сообщает об этом списком, а не удаляет молча (владелец проекта
    защищён от каскадного удаления — `Project.owner` с PROTECT).

    Что остаётся по уважению к закону о персональных данных: запись о
    факте удаления в журнале без содержимого проектов. Сам аккаунт
    стирается; сохранять его ради «истории» значило бы удерживать
    персональные данные сверх срока.
    """

    permission_classes = [IsAuthenticatedUser]
    throttle_scope = 'login'

    def delete(self, request):
        serializer = AccountDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data['password']):
            return Response({'detail': 'Пароль не совпадает.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not serializer.validated_data['confirm']:
            return Response(
                {'detail': 'Подтвердите удаление: данные восстановить '
                           'нельзя.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        projects = list(user.owned_projects.select_related('owner'))
        shared = [p for p in projects if _has_members(p)]
        if shared:
            # Чужая работа: молча удалять её нельзя, а оставлять без
            # владельца тоже. Пользователю нужно вернуть проекты или
            # передать их.
            return Response(
                {
                    'detail': 'Эти проекты имеют соавторов — удалить их '
                               'вместе с аккаунтом нельзя. Передайте '
                               'право или удалите проекты.',
                    'projects': [p.name for p in shared],
                    'reason': 'shared_projects',
                },
                status=status.HTTP_409_CONFLICT,
            )
        if projects and not serializer.validated_data['with_projects']:
            return Response(
                {
                    'detail': 'Вместе с аккаунтом будут удалены ваши '
                               'проекты. Подтвердите удаление.',
                    'projects': [p.name for p in projects],
                    'reason': 'confirm_projects',
                },
                status=status.HTTP_409_CONFLICT,
            )

        email = user.email
        names = [p.name for p in projects]
        audit_account('account.deleted', user, request,
                      detail=f'проектов: {len(names)}')
        # Проекты удаляются явно: владелец защищён от каскада, иначе
        # удаление аккаунта падало бы с ошибкой базы.
        for project in projects:
            project.delete()
        user.delete()
        logger.info('аккаунт удалён: %s (проектов было %s: %s)',
                    email, len(names), ', '.join(names) or '—')
        return Response(status=status.HTTP_204_NO_CONTENT)


__all__ = [
    'AccountDeleteSerializer',
    'AccountDeleteView',
    'PasswordResetConfirmSerializer',
    'PasswordResetConfirmView',
    'PasswordResetRequestSerializer',
    'PasswordResetRequestView',
]