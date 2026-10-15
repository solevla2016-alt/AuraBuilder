"""API Telegram Mini App (ТЗ п.16.6).

Три группы маршрутов:

* `/api/projects/<id>/telegram-bot/` — подключение бота к проекту
  (только владелец, только с тарифа Pro);
* `/api/telegram/auth/` — проверка initData и выпуск edge-токена;
* `/telegram/<логин>/` — сама Mini App.
"""

from __future__ import annotations

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import ProjectAccess, can
from accounts.serializers import audit
from billing.service import check_scenario
from projects.models import Project
from secretstore.crypto import SecretsUnavailable

from .auth import issue_edge_token
from .bot_api import BotApiError, set_web_app_menu, verify_token
from .initdata import InitDataInvalid, verify
from .models import TelegramBot


def _project(project_id: str) -> Project | None:
    return Project.objects.filter(id=project_id).first()


def _bot(project: Project, bot_id: str) -> TelegramBot | None:
    return TelegramBot.objects.filter(
        id=bot_id, project=project,
    ).select_related('project', 'owner').first()


def _forbidden(message: str, **extra):
    return Response({'detail': message, **extra},
                    status=status.HTTP_403_FORBIDDEN)


@api_view(['GET', 'POST'])
@permission_classes([ProjectAccess])
def telegram_bots(request, project_id: str):
    """Список и подключение ботов проекта."""
    project = _project(project_id)
    if project is None or not can(request.user, project, 'view'):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        bots = TelegramBot.objects.filter(project=project).order_by('name')
        return Response({'bots': [bot.public_dict() for bot in bots]})

    # Подключение бота — сценарий 4, он с тарифа Pro (ТЗ п.17.1).
    denial = check_scenario(request.user, 4)
    if denial is not None:
        return Response({'detail': denial.detail, 'reason': denial.reason},
                        status=status.HTTP_402_PAYMENT_REQUIRED)

    if request.user != project.owner:
        return _forbidden('Подключать бота может владелец проекта.')

    body = request.data or {}
    name = str(body.get('name') or '').strip()
    username = str(body.get('botUsername') or '').strip().lstrip('@')
    token = str(body.get('token') or '').strip()
    if not name or not username or not token:
        return Response(
            {'detail': 'Нужны название, логин бота и его токен.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    bot = TelegramBot(project=project, owner=project.owner, name=name,
                      bot_username=username)
    try:
        bot.set_token(token)
    except SecretsUnavailable as e:
        return Response({'detail': str(e), 'reason': 'no_encryption_key'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        identity = verify_token(token)
    except BotApiError as e:
        # Токен не проверен у Telegram: сохранять его незачем, деплой
        # потом упрётся в ошибку при первом же вызове.
        return Response(
            {'detail': f'Telegram не признаёт токен: {e}'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    bot.bot_id = identity.id or None
    if identity.username and identity.username.lower() != username.lower():
        return Response(
            {'detail': f'Логин указан неверно: токен бота @{identity.username}.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        bot.save()
    except IntegrityError:
        # Уникальность логина проверяет и БД: гонка между двумя
        # одновременными подключениями не ловится проверкой выше.
        return Response({'detail': 'Такой логин уже подключён.'},
                        status=status.HTTP_409_CONFLICT)

    audit(request, 'telegram.bot.create', project, bot.bot_username)
    return Response(bot.public_dict(), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([ProjectAccess])
def telegram_bot_detail(request, project_id: str, bot_id: str):
    """Правка и отключение бота."""
    project = _project(project_id)
    if project is None or not can(request.user, project, 'view'):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    bot = _bot(project, bot_id)
    if bot is None:
        return Response({'detail': 'бот не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if request.user != project.owner:
        return _forbidden('Менять подключение бота может владелец проекта.')

    if request.method == 'DELETE':
        audit(request, 'telegram.bot.delete', project, bot.bot_username)
        bot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    body = request.data or {}
    if 'name' in body:
        bot.name = str(body['name']).strip() or bot.name
    if body.get('token'):
        token = str(body['token']).strip()
        try:
            bot.set_token(token)
        except SecretsUnavailable as e:
            return Response({'detail': str(e), 'reason': 'no_encryption_key'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            bot.bot_id = verify_token(token).id or bot.bot_id
        except BotApiError as e:
            return Response({'detail': f'Telegram не признаёт токен: {e}'},
                            status=status.HTTP_400_BAD_REQUEST)
        # Токен сменился — прежняя настройка меню относилась к старому.
        bot.menu_configured_at = None
    bot.save()
    return Response(bot.public_dict())


@api_view(['POST'])
@permission_classes([ProjectAccess])
def telegram_bot_menu(request, project_id: str, bot_id: str):
    """Настраивает кнопку меню бота (ТЗ п.16.6)."""
    project = _project(project_id)
    if project is None or not can(request.user, project, 'view'):
        return Response({'detail': 'проект не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    bot = _bot(project, bot_id)
    if bot is None:
        return Response({'detail': 'бот не найден'},
                        status=status.HTTP_404_NOT_FOUND)
    if request.user != project.owner:
        return _forbidden('Настраивать бота может владелец проекта.')
    if not bot.has_token:
        return Response({'detail': 'Сначала укажите токен бота.'},
                        status=status.HTTP_409_CONFLICT)

    try:
        set_web_app_menu(
            bot.get_token(), bot.mini_app_url,
            str((request.data or {}).get('buttonText') or 'Открыть'),
        )
    except BotApiError as e:
        # Telegram недоступен: честно говорим об этом и не отмечаем
        # меню настроенным — иначе интерфейс покажет зелёную галочку
        # при ненастроенном меню.
        return Response({'detail': f'Telegram не принял настройку: {e}'},
                        status=status.HTTP_502_BAD_GATEWAY)

    bot.menu_configured_at = timezone.now()
    bot.save(update_fields=['menu_configured_at', 'updated_at'])
    audit(request, 'telegram.bot.menu', project, bot.bot_username)
    return Response(bot.public_dict())


@api_view(['POST'])
@permission_classes([AllowAny])
def telegram_auth(request):
    """Проверяет initData и выпускает edge-токен.

    Маршрут публичный: посетитель не зарегистрирован в платформе, и
    отказывать ему в проверке подписи не на чем — именно она и
    подтверждает, что запрос пришёл из Telegram.
    """
    body = request.data or {}
    bot_username = str(body.get('bot') or '').strip().lstrip('@')
    init_data = str(body.get('initData') or '')
    if not bot_username or not init_data:
        return Response({'detail': 'Нужны логин бота и initData.'},
                        status=status.HTTP_400_BAD_REQUEST)

    bot = TelegramBot.objects.filter(
        bot_username__iexact=bot_username,
    ).select_related('project').first()
    if bot is None or not bot.has_token:
        # Разные ответы для «бота нет» и «нет токена» показывали бы
        # посетителю, какие логины заняты.
        return Response({'detail': 'Бот не найден.'},
                        status=status.HTTP_404_NOT_FOUND)

    try:
        user, params = verify(init_data, bot.get_token())
    except InitDataInvalid as e:
        return Response({'detail': str(e), 'reason': 'init_data_invalid'},
                        status=status.HTTP_403_FORBIDDEN)

    token = issue_edge_token(
        telegram_user_id=user.id,
        bot_username=bot.bot_username,
        project_id=str(bot.project_id),
    )
    return Response({
        'token': token,
        'user': user.as_dict(),
        'project': {
            'id': str(bot.project_id),
            'name': bot.project.name,
        },
        'bot': bot.bot_username,
        'startParam': params.get('start_param', ''),
    })


__all__ = [
    'telegram_auth',
    'telegram_bot_detail',
    'telegram_bot_menu',
    'telegram_bots',
]