"""Сериализаторы узлов данных: источники, поля и записи."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    FIELD_TYPES,
    MAX_FIELDS,
    MAX_RECORDS,
    DataRecord,
    DataSource,
    source_slug,
)


class FieldSerializer(serializers.Serializer):
    """Описание одного поля источника."""

    key = serializers.CharField(max_length=40)
    label = serializers.CharField(max_length=80)
    type = serializers.ChoiceField(choices=FIELD_TYPES)
    required = serializers.BooleanField(required=False, default=False)

    def validate_key(self, value: str) -> str:
        key = value.strip()
        if not key or not key.isascii() or not key.replace('_', '').isalnum():
            raise serializers.ValidationError('Ключ: латиница, цифры и подчёркивание.')
        return key


class DataSourceSerializer(serializers.ModelSerializer):
    # Клиент читает поля в camelCase (apps/web/src/ui/data.ts), поэтому
    # имена перечислены явно через source: ModelSerializer не умеет
    # сам сопоставлять createdAt с created_at.
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)
    # Ключ необязателен: он выводится из названия, когда клиент его не
    # прислал. Обязательным он остаётся в модели — пустой ключ попал бы
    # в URL публикации.
    key = serializers.CharField(max_length=60, required=False, allow_blank=True)
    fields = FieldSerializer(many=True, required=False)
    recordCount = serializers.SerializerMethodField()

    class Meta:
        model = DataSource
        fields = ['id', 'name', 'key', 'description', 'fields', 'recordCount', 'createdAt', 'updatedAt']
        read_only_fields = ['id', 'recordCount', 'createdAt', 'updatedAt']

    def get_recordCount(self, obj: DataSource) -> int:
        # Подсчёт берётся из аннотации, если она уже была: один
        # дополнительный запрос на источник при списке не нужен.
        annotated = getattr(obj, 'record_count', None)
        return int(annotated) if annotated is not None else obj.records.count()

    def validate_fields(self, value):
        if len(value) > MAX_FIELDS:
            raise serializers.ValidationError(f'Не больше {MAX_FIELDS} полей.')
        keys = [f['key'] for f in value]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError('Ключи полей повторяются.')
        return value

    def create(self, validated_data):
        validated_data['key'] = validated_data.get('key') or source_slug(
            validated_data.get('name', '')
        )
        return super().create(validated_data)

    def validate(self, attrs):
        # key уникален в проекте. Проверка здесь, а не через
        # UniqueConstraint: сообщение об ошибке должно называть поле,
        # иначе клиент покажет 400 без объяснения.
        key = attrs.get('key') or source_slug(attrs.get('name', ''))
        project = self.context.get('project')
        qs = DataSource.objects.filter(project=project, key=key)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({'key': 'Ключ уже используется в проекте.'})
        return attrs


class DataRecordSerializer(serializers.ModelSerializer):
    # Клиент читает externalId, createdAt и updatedAt (apps/web/src/ui/data.ts).
    externalId = serializers.CharField(
        source='external_id',
        max_length=100,
        required=False,
        allow_blank=True,
    )
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = DataRecord
        fields = ['id', 'externalId', 'data', 'position', 'createdAt', 'updatedAt']
        read_only_fields = ['id', 'position', 'created_at', 'updated_at']

    def validate_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Значения должны быть объектом.')
        return value

    def validate(self, attrs):
        source = self.context.get('source')
        if source is None and self.instance is not None:
            source = self.instance.source

        external_id = attrs.get('external_id', getattr(self.instance, 'external_id', ''))
        if external_id:
            qs = DataRecord.objects.filter(source=source, external_id=external_id)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'externalId': 'Запись с таким внешним ключом уже есть.'}
                )

        record = DataRecord(
            source=source,
            external_id=external_id or '',
            data=attrs.get('data', getattr(self.instance, 'data', {})),
        )
        # Полная проверка (типы, обязательные поля, неизвестные поля)
        # живёт в модели: и API, и будущая визуальная CMS должны
        # проверять одинаково.
        record.clean()
        return attrs

    def create(self, validated_data):
        source = self.context['source']
        return DataRecord.objects.create(
            source=source,
            position=DataRecord.next_position(source),
            **validated_data,
        )