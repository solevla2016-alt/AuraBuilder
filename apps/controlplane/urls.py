"""Маршруты Control Plane.

Префикс /api/ — редактор обращается только сюда (VITE_API_BASE).

Порядок важен: health объявлен до include с маршрутом <str:project_id>,
иначе строка 'health' разбиралась бы как UUID и давала 400 вместо 200.

Admin намеренно не подключён: он нужен для эксплуатации, а не для
разработки, и тянет за собой лишние таблицы. Вернётся вместе с
разграничением доступа к нему самому (ТЗ п.7.7.3, п.11.1).
"""

from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from projects.views import health, module_catalog


@api_view(['GET'])
@permission_classes([])
def root(request):
    return Response({'service': 'aurabuilder-controlplane', 'status': 'ok'})


urlpatterns = [
    path('', root, name='root'),
    # Каталог модулей лежит на верхнем уровне API, а не внутри проектов:
    # он общий для всех проектов и редактор спрашивает его при старте.
    path('api/modules/', module_catalog, name='module-catalog'),
    path('api/health/', health, name='health'),
    # Аутентификация и профиль. Объявлены до проектов: путь
    # api/auth/login/ не должен попадать под <str:project_id>.
    path('api/auth/', include('accounts.urls')),
    path('api/projects/', include('projects.urls')),
    # Узлы данных: часть источников адресуется через проект, часть —
    # напрямую, поэтому маршруты объявлены отдельным включением.
    path('api/', include('data_sources.urls')),
    path('api/', include('component_library.urls')),
]