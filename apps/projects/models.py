"""Модель проекта и дерева страницы.

ТЗ п.3.2: состояние проекта хранится в Control Plane.

Дерево блоков хранится в JSONField: структура будет меняться вместе
с каталогом модулей (docs/MODULE-CATALOG.md), и реляционная разбивка
сейчас дала бы преждевременную фиксацию схемы. Валидация — на входе
в API, а не на уровне БД: браузеру доверять нельзя.
"""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.permissions import LIMIT_ERROR


def count_modules(tree: dict) -> int:
    """Число модулей в дереве.

    Считаются только узлы верхнего уровня: модули не вкладываются друг
    в друга, а блоки внутри модуля живут в его собственном поле props.
    Подсчёт по вложенности дал бы двойной счёт и срабатывал бы на
    обычном проекте.
    """
    blocks = tree.get('blocks') if isinstance(tree, dict) else None
    return len(blocks) if isinstance(blocks, list) else 0


def default_tree() -> dict:
    """Дерево нового проекта.

    Модули взяты из реестра (apps/projects/module_registry.py), который
    генерируется из docs/MODULE-CATALOG.md. Здесь только раскладка:
    конкретный набор стартовых блоков изменится вместе с редактором.
    """
    return {
        'width': 720,
        'blocks': [
            {'id': 'b1', 'module': 'section.hero', 'x': 40, 'y': 40,
             'width': 640, 'height': 200, 'label': 'Первый экран'},
            {'id': 'b2', 'module': 'text.heading', 'x': 40, 'y': 264,
             'width': 640, 'height': 64, 'label': 'Заголовок'},
            {'id': 'b3', 'module': 'media.image', 'x': 40, 'y': 352,
             'width': 300, 'height': 180, 'label': 'Изображение'},
            {'id': 'b4', 'module': 'text.paragraph', 'x': 364, 'y': 352,
             'width': 316, 'height': 180, 'label': 'Описание'},
        ],
    }


REVIEW_DRAFT = 'draft'
REVIEW_PENDING = 'pending'
REVIEW_CHANGES = 'changes'
REVIEW_APPROVED = 'approved'
REVIEW_STATUS_CHOICES = (
    (REVIEW_DRAFT, 'Черновик'),
    (REVIEW_PENDING, 'На согласовании'),
    (REVIEW_CHANGES, 'Нужны правки'),
    (REVIEW_APPROVED, 'Согласовано'),
)
#: Статусы, при которых опубликовать сайт нельзя без явного подтверждения.
#: «Черновик» здесь нет: ревью может и не требоваться, и запрет публикации
#: превратил бы обычную работу в обязательную процедуру.
REVIEW_BLOCKING = frozenset({REVIEW_PENDING, REVIEW_CHANGES})


class Project(models.Model):
    """Проект пользователя.

    Идентификатор — UUID: он попадает в URL публикации и в архив
    экспорта, поэтому перечисляющийся int не подходит (ТЗ п.16.2).
    """

    # default обязателен: при editable=False Django не генерирует значение,
    # и вставка падала бы с «NOT NULL constraint failed: projects_project.id».
    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    name = models.CharField('название', max_length=200)
    tree = models.JSONField('дерево страницы', default=default_tree)
    # Брендбук (акцент, шрифт, подпись, UTM) — принадлежность проекта, а
    # не отдельного блока: один и тот же цвет и подпись действуют на
    # всех страницах. Словарь, а не столбцы: набор настроек будет расти,
    # и каждая новая не должна требовать миграции.
    brand = models.JSONField('брендбук', default=dict, blank=True)
    # Статус согласования. Отдельным полем, а не вычисляемым из
    # комментариев: комментарии закрывают по одному, а согласование —
    # решение целиком, и оно должно переживать закрытие замечаний.
    review_status = models.CharField(
        'статус ревью', max_length=8,
        choices=REVIEW_STATUS_CHOICES, default=REVIEW_DRAFT,
    )
    review_approved_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_projects',
    )
    review_approved_at = models.DateTimeField('согласовано', null=True, blank=True)
    # Владелец — часть проекта, а не только запись в таблице участников:
    # если её хранить только там, проект останется без того, кто может его
    # удалить. null=True оставлен ради уже существующих записей, они
    # переводятся на следующей миграции.
    owner = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='owned_projects',
    )
    # Номер последней сохранённой версии документа. Нужен для
    # optimistic concurrency: клиент присылает версию, которую видел,
    # и сервер отвечает 409, если документ уже изменили (ТЗ п.3.2).
    version = models.PositiveIntegerField('версия', default=1)
    created_at = models.DateTimeField('создан', auto_now_add=True)
    updated_at = models.DateTimeField('изменён', auto_now=True)

    class Meta:
        verbose_name = 'проект'
        verbose_name_plural = 'проекты'
        ordering = ['-updated_at']

    def clean(self) -> None:
        """Проверка технических лимитов (ТЗ п.4.11).

        Лимит проверяется здесь, а не только в сериализаторе: дерево
        приходит ещё и из внутренних сценариев — импорта, миграций,
        тестового наполнения, — и мимо API прошло бы.
        """
        super().clean()
        modules = count_modules(self.tree)
        limit = settings.LIMITS['MAX_MODULES_PER_PROJECT']
        if modules > limit:
            raise ValidationError({
                'tree': LIMIT_ERROR.format(what='модулей', count=modules, limit=limit),
            })

    def review_blocker(self) -> dict | None:
        """Что мешает публикации: проект или первая страница со статусом.

        Проверка нужна публикации и планированию в одном виде: если бы
        каждое место считало статусы само, правило разошлось бы, и сайт
        можно было бы опубликовать в обход ревью.
        """

        if self.review_status in REVIEW_BLOCKING:
            return {
                'scope': 'project',
                'title': self.name,
                'status': self.review_status,
            }
        for page in self.pages.all():
            if page.review_status in REVIEW_BLOCKING:
                return {
                    'scope': 'page',
                    'id': str(page.id),
                    'title': page.title,
                    'status': page.review_status,
                }
        return None

    def __str__(self) -> str:
        return self.name


class Page(models.Model):
    """Дополнительная страница проекта.

    Главная страница остаётся в Project.tree: так уже сохранённые
    проекты и клиенты продолжают работать без миграции данных. Здесь
    лежат только остальные страницы, адрес каждой — /<slug>/.
    """

    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='pages',
    )
    title = models.CharField('название', max_length=200)
    slug = models.SlugField('адрес', max_length=80)
    tree = models.JSONField('дерево страницы', default=default_tree)
    seo_title = models.CharField('SEO-заголовок', max_length=200, blank=True)
    seo_description = models.CharField('SEO-описание', max_length=300, blank=True)
    order = models.PositiveIntegerField('порядок', default=0)
    version = models.PositiveIntegerField('версия', default=1)
    review_status = models.CharField(
        'статус ревью', max_length=8,
        choices=REVIEW_STATUS_CHOICES, default=REVIEW_DRAFT,
    )
    review_approved_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_pages',
    )
    review_approved_at = models.DateTimeField('согласовано', null=True, blank=True)
    created_at = models.DateTimeField('создана', auto_now_add=True)
    updated_at = models.DateTimeField('изменена', auto_now=True)

    class Meta:
        verbose_name = 'страница'
        verbose_name_plural = 'страницы'
        ordering = ['order', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'slug'],
                name='unique_page_slug_per_project',
            ),
        ]

    def clean(self) -> None:
        super().clean()
        modules = count_modules(self.tree)
        limit = settings.LIMITS['MAX_MODULES_PER_PROJECT']
        if modules > limit:
            raise ValidationError({
                'tree': LIMIT_ERROR.format(what='модулей', count=modules, limit=limit),
            })

    def __str__(self) -> str:
        return f'{self.project_id}: /{self.slug}/'


TEMPLATE_PAGE = 'page'
TEMPLATE_BLOCK = 'block'
TEMPLATE_KIND_CHOICES = (
    (TEMPLATE_PAGE, 'Страница'),
    (TEMPLATE_BLOCK, 'Блок'),
)

#: Сколько шаблонов хранится в проекте. Без предела «удачные решения»
#: через год превратились бы в свалку, по которой нельзя найти нужное.
MAX_TEMPLATES = 50


class Template(models.Model):
    """Шаблон страницы или блока (ТЗ, этап 2).

    Шаблон принадлежит проекту, а не пользователю. Причина не в правах,
    а в содержимом: блоки могут ссылаться на источники данных и файлы
    медиатеки этого проекта. Шаблон, перенесённый в другой проект, вёл
    бы себя как рабочий, но показывал пустоту или чужие адреса. Обмен
    между проектами потребует переписывать ссылки — это отдельная
    задача, а не побочный эффект «сохранить как шаблон».

    Хранится снимок: правка страницы после сохранения шаблона его не
    меняет. Иначе «удачным решением» оказалось бы текущее состояние,
    а не то, которое человек выбрал.
    """

    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='templates',
    )
    kind = models.CharField(
        'вид', max_length=8, choices=TEMPLATE_KIND_CHOICES,
        default=TEMPLATE_PAGE,
    )
    name = models.CharField('название', max_length=120)
    #: Для страницы — всё дерево, для блока — один блок верхнего уровня.
    #: Дерево плоское (модули не вкладываются), поэтому отдельная
    #: структура для блока не нужна.
    tree = models.JSONField('содержимое')
    #: Подпись источника: заголовок страницы, SEO-поля или модуль блока.
    #: Отдельным словарём, потому что набор полей у видов разный.
    meta = models.JSONField('подпись', default=dict, blank=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_templates',
    )
    created_at = models.DateTimeField('создан', auto_now_add=True)

    class Meta:
        verbose_name = 'шаблон'
        verbose_name_plural = 'шаблоны'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.kind}: {self.name}'

    def public_dict(self, detail: bool = False) -> dict:
        blocks = self.tree.get('blocks', []) if isinstance(self.tree, dict) else []
        payload = {
            'id': str(self.id),
            'kind': self.kind,
            'name': self.name,
            'title': self.meta.get('title', ''),
            'module': self.meta.get('module', ''),
            'blocks': 1 if self.kind == TEMPLATE_BLOCK else len(blocks),
            'createdAt': self.created_at.isoformat(),
        }
        if detail:
            payload['tree'] = self.tree
            payload['meta'] = self.meta
        return payload


class Comment(models.Model):
    """Замечание ревью к странице или отдельному блоку.

    Хранится на платформе и никогда не попадает в собранный пакет:
    комментарий — часть рабочего процесса, а не содержимое сайта. Попади
    он в экспорт, сайт перестал бы быть самодостаточным (ТЗ п.16.4).

    page=None означает главную страницу: её дерево лежит в Project.tree,
    а не в Page. block_id пустой — замечание ко всей странице; иначе это
    снимок идентификатора блока на момент замечания. Блок могли потом
    удалить, а замечание всё равно должно остаться читаемым.
    """

    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='comments',
    )
    block_id = models.CharField('блок', max_length=64, blank=True)
    author = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='review_comments',
    )
    text = models.TextField('текст', max_length=4000)
    # Ответ на замечание. SET_NULL, а не CASCADE: удаление корневого
    # замечания не должно молча уносить ответы других участников.
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
    )
    resolved = models.BooleanField('закрыто', default=False)
    resolved_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_comments',
    )
    resolved_at = models.DateTimeField('закрыто', null=True, blank=True)
    created_at = models.DateTimeField('создано', auto_now_add=True)

    class Meta:
        verbose_name = 'замечание'
        verbose_name_plural = 'замечания'
        ordering = ['created_at']

    def __str__(self) -> str:
        return f'{self.project_id}: {self.text[:40]}'

    def public_dict(self) -> dict:
        return {
            'id': str(self.id),
            'page': str(self.page_id) if self.page_id else None,
            'blockId': self.block_id,
            'text': self.text,
            'author': self.author.get_username() if self.author else '',
            'parent': str(self.parent_id) if self.parent_id else None,
            'resolved': self.resolved,
            'resolvedBy': (
                self.resolved_by.get_username() if self.resolved_by else ''
            ),
            'createdAt': self.created_at.isoformat(),
            'resolvedAt': self.resolved_at.isoformat() if self.resolved_at else None,
        }


class DocumentVersion(models.Model):
    """Снимок дерева проекта (ТЗ п.3.2).

    Зачем снимок, если есть история действий: история живёт в браузере
    и умирает вместе со вкладкой, а снимок хранится на сервере и
    переживает чужую правку. По ТЗ модель командной работы —
    optimistic concurrency по версиям документа (docs/TZ-GAPS.md, п.2.3),
    и для неё нужен номер, который можно предъявить при сохранении.

    Снимок неизменяем: восстановление не переписывает историю, а
    сохраняет дерево старой версии как новую. Иначе «отменить
    восстановление» было бы нечем.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='versions',
    )
    # Нор��ер снимка в пределах проекта, начиная с 1. Именно он
    # предъявляется при сохранении: сервер отвечает 409, если версия
    # успела уехать вперёд.
    number = models.PositiveIntegerField('номер')
    tree = models.JSONField('дерево')
    # Дополнительные страницы на момент снимка. Пустой список у старых
    # версий: до многостраничности страница была одна.
    pages = models.JSONField('страницы', default=list, blank=True)
    label = models.CharField('подпись', max_length=200, blank=True)
    author = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='document_versions',
    )
    created_at = models.DateTimeField('создан', auto_now_add=True)

    class Meta:
        verbose_name = 'версия документа'
        verbose_name_plural = 'версии документа'
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'number'],
                name='unique_document_version_per_project',
            ),
        ]
        ordering = ['-number']

    def __str__(self) -> str:
        return f'{self.project_id}: версия {self.number}'


class ProjectEvent(models.Model):
    """Событие проекта: сборка, публикация, деплой, копия.

    Журнал живёт на сервере, а не в браузере: публикация и деплой идут
    дольше одного экрана, а событие должно остаться, даже если вкладку
    закрыли. По нему человек понимает, что уже произошло и чем это
    закончилось, не открывая историю действий целиком.

    Событие — не журнал аудита (accounts.AuditLog): аудит отвечает на
    вопрос «кто что сделал», событие — «что сейчас с проектом». Поэтому
    здесь есть результат (успех или отказ) и текст для человека, а не
    только код действия и адрес.
    """

    KIND_BUILD = 'build'
    KIND_PUBLISH = 'publish'
    KIND_WITHDRAW = 'withdraw'
    KIND_BACKUP = 'backup'
    KIND_RESTORE = 'restore'
    KIND_DEPLOY = 'deploy'
    KIND_SCHEDULE = 'schedule'
    KIND_REVIEW = 'review'
    KIND_CHOICES = [
        (KIND_BUILD, 'Сборка'),
        (KIND_PUBLISH, 'Публикация'),
        (KIND_WITHDRAW, 'Отзыв'),
        (KIND_BACKUP, 'Резервная копия'),
        (KIND_RESTORE, 'Восстановление'),
        (KIND_DEPLOY, 'Деплой'),
        (KIND_SCHEDULE, 'Отложенная публикация'),
        (KIND_REVIEW, 'Согласование'),
    ]

    STATUS_OK = 'ok'
    STATUS_FAILED = 'failed'
    STATUS_INFO = 'info'
    STATUS_CHOICES = [
        (STATUS_OK, 'Успешно'),
        (STATUS_FAILED, 'Ошибка'),
        (STATUS_INFO, 'Сведения'),
    ]

    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name='Проект',
    )
    kind = models.CharField('Тип', max_length=16, choices=KIND_CHOICES)
    status = models.CharField(
        'Результат', max_length=8, choices=STATUS_CHOICES,
        default=STATUS_INFO,
    )
    message = models.CharField('Сообщение', max_length=300)
    # Автор может исчезнуть (учётную запись удалили), но событие
    # остаётся: иначе история проекта теряла бы факт публикации.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='project_events',
        verbose_name='Автор',
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'событие проекта'
        verbose_name_plural = 'события проекта'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', '-created_at'],
                         name='project_event_recent'),
        ]

    def __str__(self) -> str:
        return f'{self.project_id}: {self.get_kind_display()} — {self.message}'

    def public_dict(self) -> dict:
        return {
            'id': str(self.id),
            'kind': self.kind,
            'kindLabel': self.get_kind_display(),
            'status': self.status,
            'message': self.message,
            'actor': self.actor.username if self.actor else None,
            'createdAt': self.created_at.isoformat(),
        }
