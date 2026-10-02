"""Маршруты Control Plane.

Префикс /api/ — редактор обращается только сюда (VITE_API_BASE).

Порядок важен: health объявлен до include с маршрутом <str:project_id>,
иначе строка 'health' разбиралась бы как UUID и давала 400 вместо 200.

Admin намеренно не подключён: он нужен для эксплуатации, а не для
разработки, и тянет за собой лишние таблицы и зависимости. Вернётся
на этапе 1 вместе с ролями и правами (ТЗ п.11.1).
"""

from django.urls import include, path
from rest_framework.decorators import api_view
from rest_framework.response import Response

from projects.views import health, module_catalog


@api_view(['GET'])
def root(request):
    return Response({'service': 'aurabuilder-controlplane', 'status': 'ok'})


urlpatterns = [
    path('', root, name='root'),
    # Каталог модулей лежит на верхнем уровне API, а не внутри проектов:
    # он общий для всех проектов и редактор спрашивает его при старте.
    path('api/modules/', module_catalog, name='module-catalog'),
    path('api/health/', health, name='health'),
    path('api/projects/', include('projects.urls')),
]
