"""Представления Control Plane: проекты, доступ, каталог модулей.

Права проверяются по роли в проекте (ТЗ п.11.1), матрица — в
accounts/permissions.py. Здесь важны две вещи:

* Список проектов ограничен теми, к которым у пользователя есть
  доступ. Раньше отдавались все проекты подряд — это и было причиной
  перехода на роли.
* Каталог модулей остаётся публичным: он не содержит пользовательских
  данных, а редактор без входа всё равно должен показать палитру.
"""

from __future__ import annotations

import uuid

from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from accounts.models import AuditLog, Membership, Role
from accounts.permissions import (
    DELETE,
    EDIT_CONTENT,
    MANAGE_ACCESS,
    PUBLISH,
    VIEW,
    IsAuthenticatedUser,
    ProjectAccess,
    can,
    readable_projects,
)
from accounts.serializers import (
    AddMemberSerializer,
    MembershipSerializer,
    audit,
    get_client_ip,
)
from billing.service import check_page_slot, check_project_slot, check_scenario

from .models import DocumentVersion, Page, Project
from .module_registry import CATEGORIES, MODULES, modules_for_stage
from .export import ExportError
from .package import PackageTooLarge
from .package import build_package, package_zip, slugify, slugify_ascii
from .versions import restore as restore_version, snapshot
from .serializers import (
    RESERVED_SLUGS,
    PageSerializer,
    PageSummarySerializer,
    ProjectCreateSerializer,
    ProjectSerializer,
)


@api_view(['GET'])
@permission_classes([])
def health(request):
    """Проверка живости: редактор спрашивает её перед загрузкой проекта."""
    return Response({'status': 'ok'})


def _module_payload(module) -> dict:
    return {
        'id': module.id,
        'name': module.name,
        'category': module.category,
        'categoryLabel': module.category_label,
        'kind': module.kind,
        'stages': list(module.stages),
        'minStage': module.min_stage,
    }


@api_view(['GET'])
@permission_classes([])
def module_catalog(request):
    """Каталог модулей редактора.

    Публичный без входа: он не содержит пользовательских данных, а
    палитра модулей нужна редактору раньше, чем токен. Фильтр ?stage=N
    отдаёт модули, доступные на этапе выпуска: палитра не должна
    показывать то, чего ещё нет в платформе.
    """
    raw_stage = request.query_params.get('stage')
    if raw_stage is None:
        modules = MODULES
    else:
        try:
            stage = int(raw_stage)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'stage должен быть целым числом'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        modules = modules_for_stage(stage)

    category_filter = request.query_params.get('category')
    if category_filter:
        modules = tuple(m for m in modules if m.category == category_filter)

    return Response(
        {
            'total': len(modules),
            'categories': [
                {'code': c['code'], 'id': c['id'], 'label': c['label']}
                for c in CATEGORIES
            ],
            'modules': [_module_payload(m) for m in modules],
        }
    )


@api_view(['GET', 'POST'])
def project_list(request):
    """Список доступных проектов и создание нового.

    GET  — только те проекты, где пользователь владелец или участник.
    POST — создание; владельцем становится тот, кто создал.
    """
    if request.method == 'GET':
        items = (
            readable_projects(request.user)
            .select_related('owner')
            .prefetch_related('pages')[:50]
        )
        return Response(ProjectSerializer(items, many=True).data)

    serializer = ProjectCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Повторный вызов с тем же id не должен создавать дубль: инициализация
    # стенда может произойти дважды (перезагрузка страницы).
    requested_id = serializer.validated_data.get('id')
    if requested_id:
        existing = Project.objects.filter(pk=requested_id).first()
        # Существующий проект чужого пользователя не отдаётся: иначе
        # запрос по чужому UUID возвращал бы чужое дерево.
        if existing and can(request.user, existing, VIEW):
            return Response(ProjectSerializer(existing).data, status=status.HTTP_200_OK)

    # Тариф (ТЗ п.17.1): число проектов ограничено. Проверка стоит
    # после повторного вызова с тем же id — инициализация стенда не
    # должна упираться в лимит из-за уже существующего проекта.
    denial = check_project_slot(request.user)
    if denial is not None:
        return Response(
            {'detail': denial.detail, 'reason': denial.reason},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    project = serializer.save(owner=request.user)
    audit(request, 'project.create', project)
    return Response(
        ProjectSerializer(project).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([ProjectAccess])
def project_detail(request, project_id: str):
    """Чтение, изменение и удаление одного проекта."""
    try:
        project = Project.objects.filter(pk=uuid.UUID(project_id)).select_related('owner').first()
    except (ValueError, AttributeError, TypeError):
        return Response({'detail': 'некорректный UUID'}, status=status.HTTP_400_BAD_REQUEST)

    if project is None:
        # Отвечаем 404, а не 403: иначе по коду ответа можно перебором
        # узнать, какие проекты существуют.
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    # Проверка права внутри функции, а не через permission_classes:
    # декоратор не может знать проект, а объектное разрешение требует
    # get_object(), которого у функции нет.
    #
    # Отсутствие права на чтение отвечает 404, а не 403: иначе по коду
    # ответа можно перебором узнать, какие проекты существуют. 403
    # остаётся для случая «проект виден, но этого действия в роли нет».
    action = {
        'GET': VIEW,
        'HEAD': VIEW,
        'PUT': EDIT_CONTENT,
        'PATCH': EDIT_CONTENT,
        'DELETE': DELETE,
    }[request.method]
    if not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)
    if not can(request.user, project, action):
        return Response(
            {'detail': 'Недостаточно прав для этого действия.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'GET':
        return Response(ProjectSerializer(project).data)

    if request.method == 'DELETE':
        audit(request, 'project.delete', project)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # Optimistic concurrency (ТЗ п.3.2). Клиент присылает номер версии,
    # которую видел. Если документ успели изменить, сохранение молча
    # перезаписало бы чужую работу, поэтому отвечаем 409 и отдаём
    # текущую версию: редактор покажет конфликт, а не потеряет правку
    # без предупреждения.
    expected = request.data.get('expectedVersion')
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'expectedVersion должен быть числом.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if expected != project.version:
            return Response(
                {
                    'detail': 'Документ изменил другой редактор.',
                    'version': project.version,
                    'updatedAt': project.updated_at,
                },
                status=status.HTTP_409_CONFLICT,
            )

    before = project.tree
    serializer = ProjectSerializer(project, data=request.data, partial=request.method == 'PATCH')
    serializer.is_valid(raise_exception=True)
    saved = serializer.save()

    # Снимок только когда дерево действительно изменилось: иначе
    # каждый заход на страницу засор��л бы историю одинаковыми
    # версиями, и восстанавливать было бы нечего.
    if 'tree' in request.data and saved.tree != before:
        created = snapshot(
            project,
            saved.tree,
            author=request.user if request.user.is_authenticated else None,
        )
        project.version = created.number
        project.save(update_fields=['version', 'updated_at'])

    audit(request, 'project.update', project)
    return Response(ProjectSerializer(project).data)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def project_export(request, project_id: str):
    """Статический пакет проекта (ТЗ п.16.4).

    Отдаётся архив, а не ссылка на страницу: пакет должен открыться на
    чужом хостинге без платформы. Версия берётся из ?version=, иначе
    последняя сохранённая.
    """

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)
    # Выгрузка — не чтение: тарифы ограничивают её отдельно (п.17.1),
    # и право здесь то же, что у публикации.
    if not can(request.user, project, PUBLISH):
        return Response(
            {'detail': 'Выгружать проект может тот, кто публикует.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Тариф (ТЗ п.17.1): выгрузка статики — с тарифа Start.
    denial = check_scenario(request.user, 2)
    if denial is not None:
        return Response(
            {'detail': denial.detail, 'reason': denial.reason},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    raw = request.query_params.get('version')
    if raw is not None:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'version должен быть числом.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        version = DocumentVersion.objects.filter(project=project, number=number).first()
        if version is None:
            return Response({'detail': 'версия не найдена'}, status=status.HTTP_404_NOT_FOUND)
    else:
        # Последний снимок, а не текущее дерево: экспорт должен
        # воспроизводить зафиксированное состояние, иначе «собери архив
        # версии 5» отдал бы версию 6.
        version = DocumentVersion.objects.filter(project=project).order_by('-number').first()
        if version is None:
            return Response(
                {'detail': 'Сначала сохраните проект: нечего выгружать.'},
                status=status.HTTP_409_CONFLICT,
            )

    wants_pwa = request.query_params.get('pwa') in ('1', 'true', 'yes')
    if wants_pwa:
        # Тариф (ТЗ п.17.1): сценарий 4 (Telegram и PWA) — с Pro.
        # Сама сборка пакета тариф не проверяет: ею пользуются и
        # проверки, и стенд, где тарифа нет.
        denial = check_scenario(request.user, 4)
        if denial is not None:
            return Response(
                {'detail': denial.detail, 'reason': denial.reason},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

    try:
        built = build_package(
            project,
            version,
            base_url=request.query_params.get('baseUrl', ''),
            # Сценарий 4 (ТЗ п.16.6) включается запросом: по умолчанию
            # пакет остаётся без service worker, лишняя регистрация
            # которого расходует память телефона покупателя.
            pwa=wants_pwa,
        )
    except PackageTooLarge as e:
        # Превышение технического лимита — не поломка пакета, а слишком
        # большой проект. Ответ 413 с указанием источника и границы
        # позволяет показать это в интерфейсе, а не молча урезать данные.
        return Response(
            {
                'detail': f'Проект не выгружается: превышен технический лимит ({e}).',
                'limit': 'MAX_RECORDS_PER_SOURCE',
            },
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    except ExportError as e:
        # Пакет с дырой хуже отказа: собранное валидно целиком или
        # задание неуспешно (п.16.2).
        return Response({'detail': str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    _, blob = package_zip(built['files'])
    audit(request, 'project.export', project, str(version.number))
    response = HttpResponse(blob, content_type='application/zip')
    # Имя файла транслитерируется, потому что заголовок HTTP
    # ограничен ASCII: кириллица в Content-Disposition кодируется
    # платформой по-своему, и часть клиентов показывает
    # пользователю «=?utf-8?b?...?=».
    response['Content-Disposition'] = content_disposition_header(as_attachment=True, filename=f'{slugify_ascii(project.name)}-static.zip')
    response['X-AuraBuilder-Version'] = str(version.number)
    response['X-AuraBuilder-Warnings'] = str(len(built['report'].warnings))
    # Признак сценария 4: видно по одному заголовку, устанавливается
    # приложение или просто открывается вкладка.
    response['X-AuraBuilder-PWA'] = '1' if built['pwa'] else '0'
    return response


def _project_by_id(project_id: str):
    try:
        return Project.objects.filter(pk=uuid.UUID(project_id)).select_related('owner').first()
    except (ValueError, AttributeError, TypeError):
        return None


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def version_list(request, project_id: str):
    """Версии документа проекта (ТЗ п.3.2).

    Список отдаётся без самих деревьев: история растёт, а редактор
    показывает строки «кто, когда, сколько блоков». Дерево запрашивается
    отдельно и только для выбранной версии.
    """

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'POST':
        if not can(request.user, project, EDIT_CONTENT):
            return Response(
                {'detail': 'Недостаточно прав для этого действия.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        created = snapshot(
            project,
            project.tree,
            author=request.user,
            label=str(request.data.get('label', ''))[:200],
        )
        project.version = created.number
        project.save(update_fields=['version', 'updated_at'])
        audit(request, 'project.snapshot', project, str(created.number))
        return Response(
            _version_payload(created),
            status=status.HTTP_201_CREATED,
        )

    rows = [
        _version_payload(v)
        for v in DocumentVersion.objects.filter(project=project).select_related('author')[:100]
    ]
    return Response({'version': project.version, 'versions': rows})


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def version_detail(request, project_id: str, number: int):
    """Один снимок вместе с деревом."""

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)
    version = DocumentVersion.objects.filter(project=project, number=number).first()
    if version is None:
        return Response({'detail': 'версия не найдена'}, status=status.HTTP_404_NOT_FOUND)
    payload = _version_payload(version)
    payload['tree'] = version.tree
    return Response(payload)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def version_restore(request, project_id: str, number: int):
    """Вернуть проект к версии."""

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)
    if not can(request.user, project, EDIT_CONTENT):
        return Response(
            {'detail': 'Недостаточно прав для этого действия.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    version = DocumentVersion.objects.filter(project=project, number=number).first()
    if version is None:
        return Response({'detail': 'версия не найдена'}, status=status.HTTP_404_NOT_FOUND)
    created = restore_version(request, project, version)
    return Response(_version_payload(created))


def _unique_slug(project: Project, base: str) -> str:
    """Свободный адрес: «about», «about-2», «about-3»."""

    candidate = base or 'page'
    index = 2
    while (
        candidate in RESERVED_SLUGS
        or Page.objects.filter(project=project, slug=candidate).exists()
    ):
        candidate = f'{base}-{index}'
        index += 1
    return candidate


def _page_payload(page: Page) -> dict:
    data = PageSerializer(page).data
    # Версия проекта нужна редактору: после сохранения страницы она
    # сдвигается, и следующее сохранение главной должно предъявить
    # актуальный номер, иначе сервер справедливо ответит 409.
    data['projectVersion'] = page.project.version
    return data


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def page_list(request, project_id: str):
    """Страницы проекта: список без деревьев и создание новой."""

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(
            {
                'version': project.version,
                'pages': PageSummarySerializer(
                    project.pages.all(), many=True,
                ).data,
            }
        )

    if not can(request.user, project, EDIT_CONTENT):
        return Response(
            {'detail': 'Недостаточно прав для этого действия.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Главная тоже страница: она занимает место в тарифе. Поэтому
    # «сколько будет» — это уже существующие плюс главная плюс новая.
    denial = check_page_slot(request.user, project.pages.count() + 2)
    if denial is not None:
        return Response(
            {'detail': denial.detail, 'reason': denial.reason},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    payload = dict(request.data)
    if not payload.get('slug') and payload.get('title'):
        base = slugify_ascii(str(payload['title']))[:70] or 'page'
        payload['slug'] = _unique_slug(project, base)

    serializer = PageSerializer(data=payload, context={'project': project})
    serializer.is_valid(raise_exception=True)
    order = serializer.validated_data.get('order')
    if order is None:
        order = project.pages.count() + 1
    page = serializer.save(project=project, order=order)

    created = snapshot(
        project,
        project.tree,
        author=request.user,
        label=f'Создана страница «{page.title}»',
    )
    project.version = created.number
    project.save(update_fields=['version', 'updated_at'])
    audit(request, 'page.create', project, page.slug)
    return Response(_page_payload(page), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def page_detail(request, project_id: str, page_id: str):
    """Чтение, изменение и удаление одной страницы."""

    project = _project_by_id(project_id)
    if project is None or not can(request.user, project, VIEW):
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    try:
        page = project.pages.filter(pk=uuid.UUID(page_id)).first()
    except (ValueError, AttributeError, TypeError):
        page = None
    if page is None:
        return Response({'detail': 'страница не найдена'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(_page_payload(page))

    if not can(request.user, project, EDIT_CONTENT):
        return Response(
            {'detail': 'Недостаточно прав для этого действия.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'DELETE':
        slug = page.slug
        page.delete()
        created = snapshot(
            project,
            project.tree,
            author=request.user,
            label=f'Удалена страница «{slug}»',
        )
        project.version = created.number
        project.save(update_fields=['version', 'updated_at'])
        audit(request, 'page.delete', project, slug)
        return Response(status=status.HTTP_204_NO_CONTENT)

    expected = request.data.get('expectedVersion')
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'expectedVersion должен быть числом.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if expected != page.version:
            return Response(
                {
                    'detail': 'Страницу изменил другой редактор.',
                    'version': page.version,
                },
                status=status.HTTP_409_CONFLICT,
            )

    serializer = PageSerializer(
        page,
        data=request.data,
        partial=request.method == 'PATCH',
        context={'project': project},
    )
    serializer.is_valid(raise_exception=True)
    page = serializer.save()
    page.version += 1
    page.save(update_fields=['version', 'updated_at'])

    created = snapshot(
        project,
        project.tree,
        author=request.user,
        label=f'Изменена страница «{page.title}»',
    )
    project.version = created.number
    project.save(update_fields=['version', 'updated_at'])
    audit(request, 'page.update', project, page.slug)
    return Response(_page_payload(page))


def _version_payload(version: DocumentVersion) -> dict:
    blocks = version.tree.get('blocks') if isinstance(version.tree, dict) else None
    return {
        'number': version.number,
        'label': version.label,
        'author': version.author.username if version.author_id else None,
        'createdAt': version.created_at,
        'blocks': len(blocks) if isinstance(blocks, list) else 0,
    }


@api_view(['GET', 'POST'])
@permission_classes([])
def project_members(request, project_id: str):
    """Участники проекта: список и выдача роли.

    Управлять доступом может только владелец (ТЗ п.11.1: Owner —
    управление ПДн и доступом). Роль Owner через этот эндпоинт не
    выдаётся: владелец назначается при создании проекта.
    """
    try:
        project = Project.objects.filter(pk=uuid.UUID(project_id)).select_related('owner').first()
    except (ValueError, AttributeError, TypeError):
        return Response({'detail': 'некорректный UUID'}, status=status.HTTP_400_BAD_REQUEST)

    if project is None:
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    if not can(request.user, project, MANAGE_ACCESS):
        return Response(
            {'detail': 'Управлять доступом может только владелец.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'GET':
        members = Membership.objects.filter(project=project).select_related('user')
        payload = [
            {
                'id': m.id,
                'user': m.user_id,
                'username': m.user.username,
                'email': m.user.email,
                'role': m.role,
                'created_at': m.created_at,
            }
            for m in members
        ]
        # Владелец не запись об участнике, а поле проекта, поэтому в
        # списке он появляется отдельно — иначе интерфейс покажет
        # «у проекта нет владельца».
        payload.insert(
            0,
            {
                'id': None,
                'user': project.owner_id,
                'username': project.owner.username if project.owner else '',
                'email': project.owner.email if project.owner else '',
                'role': Role.OWNER,
                'created_at': project.created_at,
            },
        )
        return Response(payload)

    serializer = AddMemberSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data['user']
    role = serializer.validated_data['role']

    if user.id == project.owner_id:
        return Response(
            {'detail': 'Владелец проекта не нуждается в записи участника.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    membership, created = Membership.objects.update_or_create(
        project=project,
        user=user,
        defaults={'role': role},
    )
    audit(request, 'access.grant', project)
    return Response(
        MembershipSerializer(membership).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([])
def audit_log(request, project_id: str):
    """Журнал действий по проекту (ТЗ п.11.2): кто, когда, что, откуда.

    Читать журнал может любой, у кого есть доступ к проекту: это его
    собственная история изменений, а не служебные данные.
    """
    try:
        project = Project.objects.filter(pk=uuid.UUID(project_id)).first()
    except (ValueError, AttributeError, TypeError):
        return Response({'detail': 'некорректный UUID'}, status=status.HTTP_400_BAD_REQUEST)

    if project is None:
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    if not can(request.user, project, VIEW):
        # 404, а не 403: 403 подтвердил бы, что проект существует, и по
        # коду ответа можно было бы перебрать чужие проекты.
        return Response({'detail': 'проект не найден'}, status=status.HTTP_404_NOT_FOUND)

    entries = AuditLog.objects.filter(project=project).select_related('actor')[:100]
    return Response(
        [
            {
                'action': e.action,
                'actor': e.actor.username if e.actor else None,
                'blockId': e.block_id,
                'ip': e.ip,
                'userAgent': e.user_agent,
                'createdAt': e.created_at,
            }
            for e in entries
        ]
    )