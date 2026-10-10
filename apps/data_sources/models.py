"""Узлы данных: источники и записи.

ТЗ относит визуальную CMS к этапу 5, но шесть модулей `data.*` входят
уже в MVP (ТЗ п.12). Чтобы они не оставались пустыми каркасами, нужен
источник данных и записи — то есть ровно та модель, которая позже
превратится в визуальную БД.

Ключевые решения:

* Поля источника описываются данными, а не отдельной таблицей. Схема
  задаётся пользователем, и реляционная таблица на каждый тип поля
  означала бы миграцию базы после каждого переименования поля. Поля
  хранятся списком в JSONB: {key, label, type, required}.

* Записи — отдельная таблица, а не JSON-массив в источнике. Иначе любое
  редактирование записи переписывало бы весь источник целиком, и у
  конкурентной правки не было бы granularity: две правки разных
  записей конфликтовали бы.

* external_id нужен уже сейчас. Именно по нему идёт сверка с 1С
  (ТЗ п.7.5.3: GUID 1С ↔ external_id), и без него синхронизация
  задвоит товары при первом же повторе.

* Ключ источника (slug) уникален в пределах проекта: он попадает в
  адрес публикации и в имена переменных экспорта, поэтому должен быть
  стабильным и предсказуемым.
"""

from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from accounts.permissions import LIMIT_ERROR

#: Число записей, которое клиент запрашивает одним списком. Это не
#: технический лимит хранения (тот живёт в settings.LIMITS), а граница
#: одного ответа: браузер и выгрузка читают источник постранично.
MAX_RECORDS = 200

FIELD_TYPES = (
    ('text', 'Текст'),
    ('number', 'Число'),
    ('boolean', 'Да/нет'),
    ('date', 'Дата'),
    ('image', 'Изображение'),
    ('link', 'Ссылка'),
)

MAX_FIELDS = 40
MAX_RECORDS = 5000


#: Транслитерация кириллицы в slug. Django slugify кириллицу не
#: переводит и на русском названии возвращает пустую строку: все
#: источники получали бы ключ «source», и второй создавался бы с
#: ошибкой «ключ уже используется». Карта ниже покрывает буквы,
#: встречающиеся в русских товарных и служебных названиях.
_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '',
    'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def source_slug(name: str) -> str:
    """Ключ источника из названия: латиница, цифры, дефисы.

    Транслитерация своя, а не библиотечная: подключать ради этого
    pytz или Unidecode не хочется, а поведение должно быть
    предсказуемым — ключ попадает в URL публикации и в экспорт.
    """
    out: list[str] = []
    for ch in name.lower().replace('ё', 'е'):
        out.append(_TRANSLIT.get(ch, ch))
    value = slugify(''.join(out), allow_unicode=False)[:60]
    return value or 'source'


class DataSource(models.Model):
    """Источник данных проекта: набор полей и записей."""

    # UUID, а не счётчик: идентификатор источника попадает в URL
    # публикации, в экспорт и в настройки синхронизации с 1С (ТЗ
    # п.7.5.3, п.16.2). Перечисление источников по возрастанию
    # показывало бы заказчику, сколько их создано.
    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='data_sources',
    )
    name = models.CharField('название', max_length=120)
    key = models.CharField('ключ', max_length=60)
    description = models.CharField('описание', max_length=300, blank=True)
    # Список полей: [{key, label, type, required}, ...]
    fields = models.JSONField('поля', default=list)
    created_at = models.DateTimeField('создан', auto_now_add=True)
    updated_at = models.DateTimeField('изменён', auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'key'],
                name='unique_source_key_per_project',
            ),
        ]
        ordering = ['created_at']

    def clean(self) -> None:
        if not self.key:
            self.key = source_slug(self.name)
        if not self.key.isascii() or not self.key.replace('_', '').isalnum():
            raise ValidationError({'key': 'Ключ: латиница, цифры и подчёркивание.'})

        fields = self.fields or []
        if len(fields) > MAX_FIELDS:
            raise ValidationError({'fields': f'Не больше {MAX_FIELDS} полей.'})

        keys: set[str] = set()
        allowed = {code for code, _ in FIELD_TYPES}
        for field in fields:
            if not isinstance(field, dict):
                raise ValidationError({'fields': 'Поле описано неверно.'})
            key = str(field.get('key', '')).strip()
            if not key:
                raise ValidationError({'fields': 'У поля нет ключа.'})
            if key in keys:
                raise ValidationError({'fields': f'Ключ поля «{key}» повторяется.'})
            keys.add(key)
            if field.get('type') not in allowed:
                raise ValidationError(
                    {'fields': f'Поле «{key}»: неизвестный тип «{field.get("type")}».'}
                )

    def __str__(self) -> str:
        return f'{self.project_id}: {self.name}'


class DataRecord(models.Model):
    """Запись источника данных."""

    id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    source = models.ForeignKey(
        DataSource,
        on_delete=models.CASCADE,
        related_name='records',
    )
    # Внешний ключ: GUID из 1С или идентификатор другой системы.
    external_id = models.CharField('внешний ключ', max_length=100, blank=True)
    data = models.JSONField('значения', default=dict)
    # Порядок записей вручную. Поле created_at не годится: при импорте
    # из 1С записи приходят пачками в произвольном порядке, и страница
    # «переезжала» бы после каждой синхронизации.
    position = models.PositiveIntegerField('порядок', default=0)
    created_at = models.DateTimeField('создан', auto_now_add=True)
    updated_at = models.DateTimeField('изменён', auto_now=True)

    class Meta:
        constraints = [
            # Внешний ключ уникален внутри источника. Пустая строка не
            # участвует: записей без внешнего ключа может быть сколько
            # угодно, иначе вторая запись без ключа была бы отвергнута.
            models.UniqueConstraint(
                fields=['source', 'external_id'],
                condition=models.Q(external_id__gt=''),
                name='unique_external_id_per_source',
            ),
        ]
        ordering = ['position', 'created_at']

    def clean(self) -> None:
        data = self.data or {}
        if not isinstance(data, dict):
            raise ValidationError({'data': 'Значения записи должны быть объектом.'})
        declared = {
            str(f.get('key')) for f in (self.source.fields or []) if isinstance(f, dict)
        }
        unknown = set(data) - declared
        if unknown:
            raise ValidationError(
                {'data': f'Поля не описаны в источнике: {", ".join(sorted(unknown))}.'}
            )
        required = {
            str(f.get('key'))
            for f in (self.source.fields or [])
            if isinstance(f, dict) and f.get('required')
        }
        missing = [key for key in required if key not in data]
        if missing:
            raise ValidationError({'data': f'Обязательные поля без значения: {", ".join(sorted(missing))}.'})

        for field in self.source.fields or []:
            if not isinstance(field, dict):
                continue
            key = str(field.get('key'))
            if key not in data:
                continue
            value = data[key]
            if field.get('type') == 'number' and isinstance(value, str):
                raise ValidationError({'data': f'Поле «{key}»: ожидается число.'})
            if field.get('type') == 'boolean' and not isinstance(value, bool):
                raise ValidationError({'data': f'Поле «{key}»: ожидается да или нет.'})
            if isinstance(value, (dict, list)):
                raise ValidationError({'data': f'Поле «{key}»: значение должно быть простым.'})

        # Технический лимит на число записей (ТЗ п.4.11). Считается
        # только при создании: при правке запись уже учтена, а лишний
        # COUNT на каждом сохранении не нужен.
        #
        # Признак новой записи — _state.adding, а не self.pk: у поля
        # id задан default=uuid4, поэтому pk заполняется уже при
        # создании объекта в памяти. Проверка на self.pk никогда не
        # срабатывала, и лимит пропускал всё, что создавали через API.
        if self._state.adding and self.source_id:
            limit = settings.LIMITS['MAX_RECORDS_PER_SOURCE']
            total = DataRecord.objects.filter(source_id=self.source_id).count()
            if total >= limit:
                raise ValidationError({
                    'source': LIMIT_ERROR.format(
                        what='записей в источнике', count=total + 1, limit=limit
                    ),
                })

    def __str__(self) -> str:
        return f'{self.source_id}#{self.pk}'

    @staticmethod
    def next_position(source: DataSource) -> int:
        last = DataRecord.objects.filter(source=source).aggregate(models.Max('position'))
        # Именно сравнение с None: запись `0 or -1` даёт -1, и вторая
        # запись снова получила бы нулевую позицию — записи не умели бы
        # сохранять заданный порядок.
        highest = last['position__max']
        return (highest if highest is not None else -1) + 1