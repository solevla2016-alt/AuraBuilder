"""
Настройки Control Plane (Django 6.1).

ТЗ п.3.2: Django 5 + DRF, PostgreSQL 15+, схема public.

Ключевые решения:

* Секреты и параметры подключения читаются из переменных окружения.
  Значения по умолчанию подходят только для локальной разработки —
  в продакшене Django обязан их прервать (см. проверку ниже).
* Драйвер PostgreSQL — pg8000 (BSD-3-Clause), а не psycopg (LGPL-3.0).
  ТЗ п.7.1.6 запрещает GPL-копилефт, поэтому psycopg исключён.
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
            # pg8000 не умеет CREATE DATABASE из соединения: базу создаёт
            # администратор, приложение только работает со схемой.
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
