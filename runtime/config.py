"""Конфигурация установки рантайма.

Хранится рядом с базой в `runtime.json` на сервере. В отличие от
`runtime.json` в пакете (это публичная часть контракта, см.
docs/RUNTIME.md) файл на сервере содержит ещё и секрет подписи cookie.

Секрет генерируется при первом запуске и никогда не отправляется в
браузер: в cookie попадает только идентификатор сессии с подписью.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

DEFAULTS = {
    'version': 1,
    # Пустой список означает «любой origin»: режим удобен на первом
    # запуске, но в конфигурации заказчику лучше указать свой домен.
    'allowedOrigins': [],
    'maxBodyBytes': 16 * 1024,
    'rateLimits': {
        # Ограничения из docs/RUNTIME.md. Молчаливое ограничение
        # выглядело бы как «сайт сломался», поэтому превышение
        # возвращает 429, а не пустой результат.
        'cartPerMinute': 60,
        'searchPerMinute': 10,
    },
}


class Config:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.version = int(data.get('version') or DEFAULTS['version'])
        self.site_key = str(data.get('siteKey') or '')
        self.secret = str(data.get('secret') or '')
        self.allowed_origins = [
            str(item).rstrip('/') for item in data.get('allowedOrigins') or []
        ]
        self.max_body_bytes = int(
            data.get('maxBodyBytes') or DEFAULTS['maxBodyBytes']
        )
        limits = data.get('rateLimits') or {}
        self.cart_per_minute = int(
            limits.get('cartPerMinute') or DEFAULTS['rateLimits']['cartPerMinute']
        )
        self.search_per_minute = int(
            limits.get('searchPerMinute') or DEFAULTS['rateLimits']['searchPerMinute']
        )

    @property
    def ready(self) -> bool:
        """Готов ли рантайм принимать заказы.

        Без `siteKey` он может отвечать на `/health`, но любой запрос
        с чужим ключом был бы принят, а это хуже отказа.
        """
        return bool(self.site_key and self.secret)


def load(path: str | Path) -> Config:
    """Читает конфигурацию, создавая её при первом запуске."""
    target = Path(path)
    if target.exists():
        return Config(json.loads(target.read_text(encoding='utf-8')))

    data = dict(DEFAULTS)
    data.update(
        {
            'siteKey': secrets.token_urlsafe(18),
            'secret': secrets.token_urlsafe(32),
        }
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return Config(data)
