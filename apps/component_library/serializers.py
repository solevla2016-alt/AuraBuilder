"""Сериализаторы библиотеки компонентов."""

from __future__ import annotations

import re

from rest_framework import serializers

from projects.palette_tokens import SOLID_TOKENS, THEMES

from .contrast import MIN_CONTRAST, contrast_ratio, worst_contrast
from .models import COLOR_KEYS, TOKEN_LIMITS, ComponentStyle, default_tokens

HEX = re.compile(r'^#[0-9a-f]{6}$', re.IGNORECASE)

#: Понятные названия токенов для интерфейса библиотеки. Ключи — те же
#: имена, что в палитре: подстановка названия вместо значения была бы
#: возможна только при отсутствии сервера, а список и так короткий.
TOKEN_LABELS = {
    'canvas': 'Страница',
    'panel': 'Панель',
    'panelRaised': 'Приподнятая',
    'panelSunken': 'Утопленная',
    'panelOverlay': 'Наложение',
    'appBg': 'Фон приложения',
    'accentSurface': 'Акцент',
    'accentSurfaceSubtle': 'Акцент слабый',
    'accentSurfaceSunken': 'Акцент утопленный',
    'onAccentSurface': 'На акценте',
    'onAccentText': 'Текст на акценте',
    'success': 'Успех',
    'warning': 'Внимание',
    'danger': 'Ошибка',
    'info': 'Информация',
    'selectionBorder': 'Выделение',
}


class ComponentStyleSerializer(serializers.ModelSerializer):
    """Стиль компонента с проверкой цветов и контраста."""

    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = ComponentStyle
        fields = ['kind', 'tokens', 'updatedAt']
        read_only_fields = ['kind', 'updatedAt']

    def validate_tokens(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError('Стиль не может быть пустым.')

        unknown = set(value) - set(TOKEN_LIMITS) - set(COLOR_KEYS)
        if unknown:
            raise serializers.ValidationError(
                f'Неизвестные свойства стиля: {", ".join(sorted(unknown))}.'
            )

        for name, (low, high) in TOKEN_LIMITS.items():
            if name not in value:
                continue
            number = value[name]
            if isinstance(number, bool) or not isinstance(number, int):
                raise serializers.ValidationError(f'{name}: нужно целое число.')
            if not low <= number <= high:
                raise serializers.ValidationError(f'{name}: от {low} до {high}.')

        background = value.get('background')
        text = value.get('text')
        self._check_color('background', background)
        self._check_color('text', text)
        if isinstance(background, str) and isinstance(text, str):
            self._check_contrast(background, text)
        return value

    @staticmethod
    def _check_color(name: str, value) -> None:
        if value is None:
            return
        if not isinstance(value, str):
            raise serializers.ValidationError(f'{name}: нужен токен палитры или #RRGGBB.')
        if value in SOLID_TOKENS or HEX.match(value):
            return
        # Токен может отсутствовать только в одной из тем — такое
        # расхождение палитры ломало бы переключение темы, и обойти его
        # молча нельзя.
        unknown_in_theme = [theme for theme in THEMES if value not in THEMES[theme]]
        if unknown_in_theme:
            raise serializers.ValidationError(
                f'{name}: токена «{value}» нет в теме {unknown_in_theme[0]}.'
            )
        raise serializers.ValidationError(f'{name}: неизвестный цвет «{value}».')

    @staticmethod
    def _check_contrast(background: str, text: str) -> None:
        if HEX.match(background) and HEX.match(text):
            ratio = contrast_ratio(text, background)
            if ratio < MIN_CONTRAST:
                raise serializers.ValidationError(
                    f'Контраст текста с фоном {ratio}:1 — ниже порога {MIN_CONTRAST}:1.'
                )
            return
        ratio, theme = worst_contrast(background, text)
        if ratio < MIN_CONTRAST:
            raise serializers.ValidationError(
                f'Контраст текста с фоном {ratio}:1 в теме {theme or "—" } — '
                f'ниже порога {MIN_CONTRAST}:1.'
            )


def style_payload(kind: str, style: ComponentStyle | None) -> dict:
    """Ответ по одному виду компонента.

    isDefault отвечает на вопрос «стиль задан или взят по умолчанию»:
    без него редактор не может отличить «пользователь выбрал ровно то же,
    что по умолчанию» от «ничего не трогали», а сброс к умолчаниям
    выглядел бы как неработающая кнопка.
    """

    tokens = default_tokens(kind) if style is None else dict(style.tokens)
    return {
        'kind': kind,
        'tokens': tokens,
        'isDefault': style is None,
        'updatedAt': style.updated_at if style is not None else None,
    }