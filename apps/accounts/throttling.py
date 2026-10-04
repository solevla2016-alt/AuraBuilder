"""Ограничение частоты для входа и регистрации (ТЗ п.7.7).

Почему свой класс, а не настройка DEFAULT_THROTTLE_RATES: DRF понимает
только записи вида «число/период», где период — одна буква (s, m, h, d).
Требование «5 попыток за 10 минут» в этот формат не помещается: «5/10m»
даёт KeyError при первом же запросе, а «30/hour» разрешает 30 попыток
подряд за 10 минут — вшестеро больше, чем требуется.

Поэтому окно задаётся явно, в секундах, и его можно менять из
окружения без правки кода. allow_request переопределён: родительский
разбирает rate в своём формате и всё равно упал бы на «600s».
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


class LoginRateThrottle(ScopedRateThrottle):
    """5 попыток входа за 10 минут с одного адреса.

    Считается по IP. Не по логину: иначе перебор одной учётной записи
    с разных адресов проходил бы без препятствия, а защиты от разбора
    одного пароля с тысячи адресов не было бы вовсе.
    """

    scope = 'login'

    def allow_request(self, request, view):
        scope = getattr(view, self.scope_attr, None)
        if not scope:
            return True

        # Лимит и окно ставятся здесь, а не в __init__: родительский
        # allow_request успевает разобрать get_rate() и упал бы на
        # формате, которого DRF не знает.
        self.scope = scope
        self.num_requests = int(getattr(settings, 'LOGIN_ATTEMPT_LIMIT', 5))
        self.duration = int(getattr(settings, 'LOGIN_ATTEMPT_WINDOW_MINUTES', 10)) * 60
        self.rate = f'{self.num_requests} запросов за {self.duration} с'
        self.key = 'login'
        return super(ScopedRateThrottle, self).allow_request(request, view)

    def get_cache_key(self, request, view):
        # Вход и регистрация делят окно, но не смешиваются с лимитом
        # анонимных запросов: scope входит в ключ.
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}