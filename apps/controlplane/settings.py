"""
Настройки Control Plane (Django 6.1).

ТЗ п.3.2: Django 5 + DRF, PostgreSQL 15+, схема public.

Ключевые решения:

* Секреты и параметры подключения читаются из переменных окружения.
  Значения по умолчанию подходят только для локальной разработки —
  в продакшене Django обязан их прервать (см. проверку ниже).
* Драйвер PostgreSQL — psycopg (LGPL-3.0-only), исключение из п.7.1.6,
  утверждённое заказчиком 02.10.2026. Django не поддерживает драйверы
  на чистом Python: pg8000 лицензионно чист, но бэкенд его не принимает.
* RLS в PostgreSQL включается на этапе командной работы (ТЗ п.3.2);
  для одиночного стенда достаточно прав на уровне Django.
* CORS для локальной разработки редактора (порт 5173).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key: str, default: str | None = None) -> str:
    value = os.environ.get(key, default)
    if value is None:
        raise RuntimeError(f'не задана переменная окружения {key}')
    return value


def env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).lower() in {'1', 'true', 'yes', 'on'}


def env_list(key: str, default: str = '') -> list[str]:
    return [item.strip() for item in os.environ.get(key, default).split(',') if item.strip()]


# --- Безопасность -------------------------------------------------------

# В разработке ключ лежит в .env; в продакшене переменная обязательна.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-insecure-key-change-me')
DEBUG = env_bool('DJANGO_DEBUG', True)

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')

if not DEBUG and SECRET_KEY == 'dev-only-insecure-key-change-me':
    raise RuntimeError(
        'DJANGO_SECRET_KEY должен быть задан в продакшене: '
        'значение по умолчанию небезопасно'
    )

CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

# --- Продакшен-безопасность (ТЗ п.7.7) ---
# В разработке эти параметры мешают: редирект на HTTPS уводит на
# несуществующий домен, а HSTS запоминает адрес без срока действия.
# Поэтому они включаются только при DEBUG=0, а значения приходят
# из окружения — иначе сервер встанет с неверными настройками TLS.

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_HSTS_INCLUDE_SUBDOMAINS', True)
    SECURE_HSTS_PRELOAD = env_bool('DJANGO_HSTS_PRELOAD', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    X_FRAME_OPTIONS = 'DENY'

# Django почти всегда стоит за обратным прокси (nginx,ingress,балансировщик),
# и TLS терминируется на нём. Без этого заголовка Django считает соединение
# незащищённым и редиректит каждый запрос на https — то есть в ответ на
# редирект прокси снова передаёт http, и клиент зацикливается.
#
# Флаг выключен по умолчанию намеренно: заголовок X-Forwarded-Proto
# приходит от клиента, и если Django доступен напрямую (без прокси),
# любой может подделать его и обойти редирект на https. Включать только
# когда доступ к Django закрыт прокси — в docker-compose порт 8000 для
# этого и не публикуется наружу.
if env_bool('DJANGO_TRUST_FORWARDED_PROTO', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# --- Приложения ---------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'projects',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'controlplane.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'controlplane.wsgi.application'

# --- База данных --------------------------------------------------------

if env_bool('USE_SQLITE'):
    # Только для тестов и запуска без PostgreSQL на машине разработчика.
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('POSTGRES_DB', 'aurabuilder'),
            'USER': env('POSTGRES_USER', 'aurabuilder'),
            'PASSWORD': env('POSTGRES_PASSWORD', ''),
            'HOST': env('POSTGRES_HOST', '127.0.0.1'),
            'PORT': env('POSTGRES_PORT', '5432'),
            # psycopg-binary ставит libpq под Windows; на сервере Linux
            # достаточно psycopg без бинарной сборки.
            'OPTIONS': {'client_encoding': 'UTF8'},
            'CONN_MAX_AGE': 60,
        }
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- DRF ----------------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
    'UNAUTHENTICATED_USER': None,
    # Права по ролям появятся на этапе 2 (ТЗ п.11.1). Сейчас стенд
    # работает без авторизации, и это осознанное упрощение.
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
}

# --- Пароли -------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Локализация --------------------------------------------------------

# Интерфейс платформы — русский (ТЗ п.1.2).
LANGUAGE_CODE = 'ru'
TIME_ZONE = env('DJANGO_TIME_ZONE', 'Europe/Moscow')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# --- Раздача статики ---
# В контейнере отдельный сервис статики не нужен: whitenoise отдаёт
# /static из приложения со сжатием brotli и gzip. Отдельный nginx ради
# файлов админки — лишняя точка отказа и лишняя настройка.
#
# В разработке (vite отдаёт фронт сам, файлов мало) пакет выключен
# лишним требованием: WHITENOISE_ENABLED управляет этим явно, чтобы
# поведение не зависело от DEBUG.

WHITENOISE_ENABLED = env_bool('WHITENOISE_ENABLED', not DEBUG)

if WHITENOISE_ENABLED:
    INSTALLED_APPS.insert(
        INSTALLED_APPS.index('django.contrib.staticfiles') + 1,
        'whitenoise.runserver_nostatic',
    )
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }
    # Хеш в имени файла позволяет отдавать статику навсегда: браузер
    # не переспрашивает её после первого раза, и страница не ждёт сеть.
    WHITENOISE_MAX_AGE = int(os.environ.get('WHITENOISE_MAX_AGE', '31536000'))
    WHITENOISE_MIMETYPES = {
        # Смысловое имя для отчётов и логов веб-сервера вместо woff2.
        '.woff2': 'font/woff2',
        '.json': 'application/json',
        '.webmanifest': 'application/manifest+json',
    }

# --- CORS ---------------------------------------------------------------

# Редактор в разработке живёт на 5173, Control Plane — на 8000.
# django-cors-headers ставится только при DEBUG: в продакшене фронт
# и API должны отдаваться с одного домена.
if DEBUG and env_bool('DJANGO_CORS_ENABLED', True):
    INSTALLED_APPS.append('corsheaders')
    MIDDLEWARE.insert(1, 'corsheaders.middleware.CorsMiddleware')
    CORS_ALLOWED_ORIGINS = env_list(
        'DJANGO_CORS_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173'
    )

# --- Email ---------------------------------------------------------------

# Яндекс 360 SMTP — основной провайдер (ТЗ п.7.6).
EMAIL_BACKEND = os.environ.get(
    'DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.yandex.ru')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '465'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', True)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@aurabuilder.ru')

# --- Логирование --------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'},
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
    },
}
