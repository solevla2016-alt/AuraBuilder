"""HTTP-обвязка MCP: один POST — один JSON-RPC вызов."""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ParseError
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedUser

from .mcp import PARSE_ERROR, handle_message


def _jsonrpc_error(code: int, message: str) -> Response:
    response = Response(
        {
            'jsonrpc': '2.0',
            'id': None,
            'error': {'code': code, 'message': message},
        },
        status=400,
    )
    response['X-API-Version'] = '1'
    return response


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def mcp_endpoint(request):
    """Точка входа MCP.

    Ответ на уведомление — 202 без тела: JSON-RPC не разрешает отвечать
    на сообщение без id, а клиент иначе принял бы ответ за результат
    следующего вызова.
    """

    try:
        payload = request.data
    except ParseError:
        return _jsonrpc_error(PARSE_ERROR, 'Тело запроса не разобрано как JSON.')

    status, body = handle_message(payload, request.user)
    if body is None:
        response = Response(status=status)
    else:
        response = Response(body, status=status)
    response['X-API-Version'] = '1'
    # Явно, чтобы прокси не пытался кешировать ответы инструментов.
    response['Cache-Control'] = 'no-store'
    return response


__all__ = ['mcp_endpoint']
