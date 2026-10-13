"""Профиль хостинга: куда и как заказчик выкладывает сайт.

Сценарий 3 ТЗ п.16.5 — сайт работает на серверах клиента, а управляется
через AuraBuilder. Разбирать закрытые API каждого хостинга в платформе
нельзя: их шесть, они меняются и требуют выданных ключей. Поэтому
профиль описывает доступ, который у всех есть и одинаков, — FTP
(ftplib из стандартной библиотеки) и файловую систему.

Что хранится и что не хранится: пароль или ключ лежат в профиле, но
никогда не попадают в API. Наружу отдаётся только «задан или нет»:
иначе любой, кто увидел профиль, получил бы доступ к серверу.
Шифрование секретов в покое — отдельная задача (ADR-0006).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

# Транспорт, который точно работает везде: файловая система. Он же
# используется в проверках — поднимать FTP-сервер ради теста не нужно.
KIND_FS = 'fs'
KIND_FTP = 'ftp'

KIND_CHOICES = (
    (KIND_FS, 'Папка на диске'),
    (KIND_FTP, 'FTP'),
)


class HostingProfile(models.Model):
    """Доступ к серверу заказчика.

    Владелец проекта, а не всего аккаунта: на одном аккаунте могут
    быть сайты нескольких заказчиков, и доступы у них разные.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hosting_profiles',
        verbose_name='Владелец',
    )
    name = models.CharField('Название', max_length=120)
    kind = models.CharField(
        'Способ доступа', max_length=8, choices=KIND_CHOICES, default=KIND_FTP
    )
    host = models.CharField('Хост', max_length=200, blank=True)
    port = models.PositiveIntegerField('Порт', default=21)
    username = models.CharField('Логин', max_length=120, blank=True)
    secret = models.CharField('Пароль или ключ', max_length=400, blank=True)
    root_path = models.CharField(
        'Каталог сайта', max_length=300, blank=True,
        help_text='Относительный путь от домашней папки, например public_html',
    )
    runtime_path = models.CharField(
        'Каталог рантайма', max_length=300, blank=True,
        help_text='Где положить рантайм; пусто — рядом с сайтом, в .aurabuilder',
    )
    site_url = models.CharField(
        'Адрес сайта', max_length=300, blank=True,
        help_text='Нужен для проверки результата: https://example.ru',
    )
    site_key = models.CharField(
        'Ключ установки', max_length=120, blank=True,
        help_text='Создаётся при первом деплое и дальше не меняется: '
                  'иначе корзины покупателей сбрасывались бы при выгрузке',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Профиль хостинга'
        verbose_name_plural = 'Профили хостинга'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    @property
    def has_secret(self) -> bool:
        """Признак для API: секрет задан, но не показывается."""
        return bool(self.secret)

    @property
    def target_path(self) -> str:
        """Каталог сайта с ведущим и завершающим слэшем.

        Без них FTP-клиент считает путь относительным и может положить
        файлы не туда: об этом предупреждает ftplib.
        """
        path = (self.root_path or '').strip()
        if not path:
            return '/'
        if not path.startswith('/'):
            path = '/' + path
        return path if path.endswith('/') else path + '/'

    @property
    def runtime_target_path(self) -> str:
        path = (self.runtime_path or '').strip()
        if not path:
            return self.target_path + '.aurabuilder/'
        if not path.startswith('/'):
            path = '/' + path
        return path if path.endswith('/') else path + '/'

    def public_dict(self) -> dict:
        """Представление для интерфейса: без секрета."""
        return {
            'id': str(self.id),
            'name': self.name,
            'kind': self.kind,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'rootPath': self.root_path,
            'runtimePath': self.runtime_path,
            'siteUrl': self.site_url,
            'hasSecret': self.has_secret,
        }
