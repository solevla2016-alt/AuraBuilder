"""Единый формат ответов публичного API.

Внутренний API редактора отвечает так, как удобно редактору: где-то
`detail`, где-то поля сериализатора. Внешнему клиенту нужен один
контракт на все ошибки, иначе ему приходится угадывать форму по коду
ответа. Перехватчик срабатывает только для /api/v1/: правка внутренних
ответов сломала бы уже выпущенный редактор.
"""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

API_PREFIX = '/api/v1/'
API_VERSION = '1'

#: Код ошибки по HTTP-статусу. Коды стабильны: клиент может проверять
#: их вместо разбора текста сообщения, который переводится.
CODES = {
    400: 'invalid_request',
    401: 'unauthorized',
    402: 'payment_required',
    403: 'forbidden',
    404: 'not_found',
    405: 'method_not_allowed',
    409: 'conflict',
    413: 'payload_too_large',
    422: 'unprocessable',
    429: 'rate_limited',
}


def api_response(data=None, status: int = 200) -> Response:
    response = Response(data, status=status)
    response['X-API-Version'] = API_VERSION
    return response


def api_error(code: str, message: str, status: int, **extra) -> Response:
    error = {'code': code, 'message': message}
    error.update(extra)
    return api_response({'error': error}, status=status)


def _message(data) -> str:
    """Первое человекочитаемое сообщение из ответа DRF."""

    if isinstance(data, dict):
        detail = data.get('detail')
        if detail:
            return str(detail)
        for key, value in data.items():
            if isinstance(value, (list, tuple)) and value:
                return f'{key}: {value[0]}'
            if isinstance(value, str):
                return f'{key}: {value}'
    if isinstance(data, (list, tuple)) and data:
        return str(data[0])
    return str(data) if data else 'Ошибка запроса.'


def exception_handler(exc, context):
    """DRF-ошибки в /api/v1/ приводятся к общему конверту."""

    response = drf_exception_handler(exc, context)
    request = context.get('request')
    if (
        response is None
        or request is None
        or not getattr(request, 'path', '').startswith(API_PREFIX)
    ):
        return response

    code = CODES.get(response.status_code, 'error')
    response.data = {
        'error': {
            'code': code,
            'message': _message(response.data),
        }
    }
    response['X-API-Version'] = API_VERSION
    return response
