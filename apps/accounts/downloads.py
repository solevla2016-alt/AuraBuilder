"""Короткоживущие ссылки на скачивание архивов.

Почему не обычная ссылка: JWT лежит в localStorage и уходит только в
заголовке Authorization. Переход по <a href> заголовок не отправляет,
поэтому «Скачать архив», PWA-пакет и JSON-бэкап отвечали 401 — при том
что весь остальной API работал.

Держать архив в памяти вкладки через fetch+blob тоже нельзя: пакет
проекта весит десятки мегабайт, и вкладка на слабом ноутбуке падала бы
на пике памяти. Поэтому скачивание остаётся переходом браузера, а
авторизация — коротким тикетом в query.

Тикет подписан SECRET_KEY и привязан к пользователю и точному пути,
принимается только для GET и живёт две минуты. Утечка через историю или
журнал ограничена одним файлом и двумя минутами; токен доступа в URL не
попадает. Список путей — белый, а не «любой /api/»: иначе endpoint стал
бы универсальной аутентификацией по ссылке.

Модуль намеренно не импортирует rest_framework.views: DRF читает
DEFAULT_AUTHENTICATION_CLASSES при собственном импорте, и обращение к
views здесь дало бы циклический импорт. Сам view живёт в accounts.views.
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

#: Соль отделяет подпись тикета от любых других подписей Django.
TICKET_SALT = 'aurabuilder.download'

#: Сколько живёт ссылка. Две минуты — с запасом на медленный выбор файла
#: в диалоге сохранения и мало для того, чтобы ссылка из журнала пригодилась.
TICKET_TTL_SECONDS = 120

#: Единственные адреса, на которые выдаётся тикет: экспорт статики,
#: PWA-пакет (тот же адрес с ?pwa=1) и JSON-бэкап конфигурации.
ALLOWED_PATH = re.compile(r'^/api/projects/[^/?#]+/(?:export|config)/$')


def normalize_path(path: object) -> str | None:
    """Путь, если на него можно выдать тикет, иначе None."""
    value = str(path or '').strip()
    return value if ALLOWED_PATH.match(value) else None


def issue_ticket(user, path: str) -> str:
    """Подписанный тикет для пользователя и конкретного адреса."""
    return signing.dumps(
        {'u': user.pk, 'p': path},
        salt=TICKET_SALT,
        compress=True,
    )


class DownloadTicketAuthentication(BaseAuthentication):
    """Аутентификация GET-запроса по ?ticket=.

    Стоит после JWT: обычные запросы идут с заголовком, тикет нужен
    только переходам браузера, где заголовка нет. Ошибка в тикете —
    это AuthenticationFailed, а не «нет пользователя»: иначе браузер
    получил бы 403 вместо понятного 401.
    """

    def authenticate(self, request):
        raw = request.query_params.get('ticket')
        if not raw:
            return None
        # Тикет только на чтение: POST с query-ссылкой не должен
        # превращаться в способ выполнить действие без заголовка.
        if request.method not in ('GET', 'HEAD'):
            raise AuthenticationFailed('тикет принимается только для чтения')
        try:
            data = signing.loads(
                raw, salt=TICKET_SALT, max_age=TICKET_TTL_SECONDS,
            )
        except signing.SignatureExpired:
            raise AuthenticationFailed(
                'ссылка устарела, запросите новую',
            ) from None
        except signing.BadSignature:
            raise AuthenticationFailed('ссылка недействительна') from None
        # Привязка к пути: тикет на экспорт не открывает бэкап и
        # наоборот, даже если проект тот же.
        if data.get('p') != request.path:
            raise AuthenticationFailed('ссылка выдана для другого адреса')
        user = get_user_model().objects.filter(
            pk=data.get('u'), is_active=True,
        ).first()
        if user is None:
            raise AuthenticationFailed('пользователь недоступен')
        return (user, None)


__all__ = [
    'ALLOWED_PATH',
    'DownloadTicketAuthentication',
    'TICKET_SALT',
    'TICKET_TTL_SECONDS',
    'issue_ticket',
    'normalize_path',
]
