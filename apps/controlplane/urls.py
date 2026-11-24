"""Маршруты Control Plane.

Префикс /api/ — редактор обращается только сюда (VITE_API_BASE).

Порядок важен: health объявлен до include с маршрутом <str:project_id>,
иначе строка 'health' разбиралась бы как UUID и давала 400 вместо 200.

Admin намеренно не подключён: он нужен для эксплуатации, а не для
разработки, и тянет за собой лишние таблицы. Вернётся вместе с
разграничением доступа к нему самому (ТЗ п.7.7.3, п.11.1).
"""

from django.conf import settings
from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from projects.views import health, module_catalog


@api_view(['GET'])
@permission_classes([])
def root(request):
    return Response({'service': 'aurabuilder-controlplane', 'status': 'ok'})


@api_view(['GET'])
@permission_classes([])
def config(request):
    """Публичная конфигурация режима для интерфейса.

    Экран входа должен знать, показывать ли вкладку регистрации, до
    того как у пользователя появится токен. Спрашивать это у /auth/me/
    нельзя — он закрыт. Секретов здесь нет: только то, что и так видно
    по поведению сервера.
    """
    return Response(
        {
            'mode': settings.DEPLOYMENT_MODE,
            'registrationOpen': settings.REGISTRATION_OPEN,
            'billingEnabled': settings.BILLING_ENABLED,
        },
    )


urlpatterns = [
    path('', root, name='root'),
    # Режим развёртывания для экрана входа. Объявлено до include'ов,
    # чтобы config не разбирался как <str:project_id>.
    path('api/config/', config, name='config'),
    # Каталог модулей лежит на верхнем уровне API, а не внутри проектов:
    # он общий для всех проектов и редактор спрашивает его при старте.
    path('api/modules/', module_catalog, name='module-catalog'),
    path('api/health/', health, name='health'),
    # Публичный API v1: отдельное пространство имён, потому что его
    # форма ответа не должна меняться вместе с внутренним API.
    path('api/v1/', include('api_v1.urls')),
    # Аналитика опубликованных сайтов и приём заявок. Заявки — публичный
    # маршрут: их отправляет посетитель сайта, а не участник проекта.
    # Объявлено до проектов, чтобы /api/forms/ не попал под
    # <str:project_id>.
    path('api/', include('analytics.urls')),
    # Аутентификация и профиль. Объявлены до проектов: путь
    # api/auth/login/ не должен попадать под <str:project_id>.
    path('api/auth/', include('accounts.urls')),
    # Академия: уроки и прогресс пользователя. До проектов, потому что
    # /api/academy/ не должен попасть под <str:project_id>.
    path('api/', include('academy.urls')),
    # Вебхуки проекта. Объявлены до api/projects/, чтобы адрес
    # projects/<id>/webhooks/ не разбирался как подресурс проекта.
    path('api/', include('webhooks.urls')),
    # ИИ-помощник проекта: чтение состояния и запуск действий.
    # До api/projects/, иначе «assistant» попал бы под <str:project_id>.
    path('api/', include('assistant.urls')),
    path('api/projects/', include('projects.urls')),
    # Деплой на хостинг заказчика (ТЗ п.16.5): профили доступа и
    # сама выкладка. Объявлено после проектов, потому что все пути
    # начинаются с api/projects/.
    path('api/', include('deploying.urls')),
    # Тарифы и биллинг (ТЗ п.17.1). Объявлено до проектов, потому что
    # путь /api/billing/subscription/ не должен попасть под
    # <str:project_id>: поддомен проекта «billing» существует, а
    # маршрут — нет.
    path('api/billing/', include('billing.urls')),
    # Публикация: API под проектом и раздача опубликованных сайтов.
    # Раздача объявлена здесь же, чтобы префикс /sites/ не перехватывался
    # маршрутами платформы.
    path('', include('publications.urls')),
    # Telegram Mini App (ТЗ п.16.6): подключение бота под
    # проектом, проверка initData и сама страница приложения.
    path('', include('telegram.urls')),
    # Узлы данных: часть источников адресуется через проект, часть —
    # напрямую, поэтому маршруты объявлены отдельным включением.
    path('api/', include('data_sources.urls')),
    path('api/', include('component_library.urls')),
    # Логика страницы (Logic Graph): библиотека нод, граф и
    # предпросмотр скомпилированного файла. Объявлено до проектов:
    # путь api/projects/<id>/logic/ содержит два сегмента и должен
    # находиться раньше общего префикса.
    path('', include('logic.urls')),
    # Медиатека проекта: загрузка и раздача картинок. Объявлено после
    # логики, но до проектов: адрес файла содержит имя с точкой и
    # дефисом, и его не должен перехватывать общий префикс.
    path('', include('assets.urls')),
]