"""Сериализаторы профиля, согласий и участников проекта."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers

from .models import Membership, Role, UserConsent

User = get_user_model()

CONSENT_VERSION = '1.0'

#: Поле-ловушка. Имя выглядит как обычное поле для автозаполнения,
#: поэтому браузер может подставить его сам, а бот заполнит точно.
HONEYPOT_FIELD = 'website'


class UserSerializer(serializers.ModelSerializer):
    """Профиль пользователя.

    Пароль, дата последнего входа и признак суперпользователя наружу не
    отдаются: это либо секрет, либо лишняя информация о другом человеке.
    """

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    """Регистрация нового пользователя."""

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    # Минимум 12 символов: требование ТЗ п.7.7 к паролям. Проверка
    # сложности в Django (AUTH_PASSWORD_VALIDATORS) остаётся в силе —
    # 12 символов не отменяют требование не быть паролем из словаря.
    password = serializers.CharField(write_only=True, min_length=12, trim_whitespace=False)
    consent_pdn = serializers.BooleanField(
        help_text='Согласие на обработку персональных данных (152-ФЗ).',
    )
    website = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        help_text='Ловушка для ботов. Человек это поле не видит.',
    )

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Логин уже занят.')
        return value

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Email уже используется.')
        return value

    def validate(self, attrs: dict) -> dict:
        # Согласие проверяется здесь, а не во вью: иначе ошибка приходит
        # с кодом 400 из другого места и с другим текстом, и клиенту
        # приходится разбирать, какое из полей виновато.
        if not attrs.get('consent_pdn'):
            raise serializers.ValidationError(
                {
                    'consent_pdn': (
                        'Без согласия на обработку персональных данных '
                        'регистрация невозможна.'
                    )
                }
            )
        if attrs.get(HONEYPOT_FIELD):
            # Ответ неотличим от обычной ошибки валидации: иначе бот
            # понял бы, что его вычислили, и начал подбирать поля.
            raise serializers.ValidationError('Проверьте правильность формы.')
        return attrs

    def create(self, validated_data: dict) -> User:
        password = validated_data.pop('password')
        # Согласие и ловушка — поля формы, а не пользователя. Без их
        # удаления create_user получил бы лишние аргументы и упал.
        validated_data.pop('consent_pdn', None)
        validated_data.pop(HONEYPOT_FIELD, None)
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    """Вход по логину или по email."""

    login = serializers.CharField(help_text='Логин или email.')
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        login = attrs['login']
        user = User.objects.filter(username__iexact=login).first()
        if user is None and '@' in login:
            user = User.objects.filter(email__iexact=login).first()

        # Пароль проверяется всегда, даже если пользователя нет: иначе
        # по времени ответа видно, какие логины существуют.
        if user is not None and user.check_password(attrs['password']):
            if not user.is_active:
                raise serializers.ValidationError('Учётная запись отключена.')
            attrs['user'] = user
            return attrs

        raise serializers.ValidationError('Неверный логин или пароль.')


class ConsentSerializer(serializers.ModelSerializer):
    """Запись согласия на обработку ПДн."""

    class Meta:
        model = UserConsent
        fields = ['document_version', 'granted_at', 'revoked_at', 'active']
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    """Участник проекта."""

    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'user', 'username', 'email', 'role', 'created_at']
        read_only_fields = ['id', 'user', 'username', 'email', 'created_at']


class AddMemberSerializer(serializers.Serializer):
    """Добавление участника по логину или email."""

    login = serializers.CharField(help_text='Логин или email пользователя.')
    role = serializers.ChoiceField(choices=Role.choices)

    def validate(self, attrs: dict):
        login = attrs['login']
        user = User.objects.filter(username__iexact=login).first()
        if user is None and '@' in login:
            user = User.objects.filter(email__iexact=login).first()
        if user is None:
            raise serializers.ValidationError({'login': 'Пользователь не найден.'})
        attrs['user'] = user
        return attrs

    def validate_role(self, value: str) -> str:
        # Владелец не выдаётся через участников: он назначается
        # при создании проекта. Иначе у проекта появятся два владельца
        # или ни одного, а это ломает удаление и биллинг.
        if value == Role.OWNER:
            raise serializers.ValidationError(
                'Роль владельца назначается при создании проекта.'
            )
        return value


def get_client_ip(request) -> str | None:
    """IP клиента.

    За nginx берётся X-Forwarded-For: там единственное место, где виден
    настоящий адрес. Без прокси Django знает его сам.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def record_consent(request, user) -> UserConsent:
    """Записывает согласие на обработку ПДн с датой, версией и IP."""
    return UserConsent.objects.create(
        user=user,
        document_version=CONSENT_VERSION,
        ip=get_client_ip(request),
    )


def audit(request, action: str, project, block_id: str = '') -> None:
    """Запись в журнал действий (ТЗ п.11.2).

    Пишется на сервере при каждом изменении проекта: клиент может не
    отправить это событие, а доказать, кто именно читал персональные
    данные, обязано само приложение.
    """
    from .models import AuditLog

    user_agent = request.META.get('HTTP_USER_AGENT', '')
    AuditLog.objects.create(
        action=action,
        actor=request.user if request.user.is_authenticated else None,
        project=project,
        block_id=block_id[:64],
        ip=get_client_ip(request),
        user_agent=user_agent[:300],
    )


def suggest_slug(name: str) -> str:
    """Имя проекта латиницей — будущий адрес публикации (ТЗ п.16.2)."""
    value = slugify(name, allow_unicode=False)[:60]
    return value or 'project'