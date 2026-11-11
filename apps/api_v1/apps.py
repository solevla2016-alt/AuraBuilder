from django.apps import AppConfig


class ApiV1Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api_v1'
    verbose_name = 'Публичный API v1'
