"""Ограничение частоты для публичных форм.

Форма открыта анонимным посетителям, поэтому ограничение обязательно:
без него один скрипт наполняет базу заявок мусором. Лимит считается по
IP и действует только на POST: страницу с формой можно открывать
сколько угодно.

Свой класс, а не общий `anon`: у заявок другой смысл. Общий лимит
платформы (100 запросов в час) рассчитан на API редактора, а форма с
лендинга может отправить несколько заявок с одного адреса — например,
из офиса, где все выходят через один NAT.
"""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class FormRateThrottle(SimpleRateThrottle):
    scope = 'forms'

    def get_cache_key(self, request, view):
        if request.method != 'POST':
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }
