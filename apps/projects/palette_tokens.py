"""Значения токенов палитры для Control Plane.

* СГЕНЕРИРОВАНО — не править руками. Источник: docs/palette.json
 * Генератор: packages/tokens/build.mjs
 * Правьте источник, затем: npm run tokens:build

Нужен серверу для одной вещи: проверить контраст между фоном и текстом,
которые пользователь выбрал в библиотеке компонентов (ТЗ п.3.1).
Считать его на глаз нельзя, а взять палитру из браузера сервер не может.

Список ограничен непрозрачными цветами: полупрозрачные токены
описывают наложения, а не поверхности, и контраст с ними зависит от
того, что окажется под ними.
"""

from __future__ import annotations

#: Имена токенов, пригодных как заливка или как цвет текста.
SOLID_TOKENS: tuple[str, ...] = (
    "appBg",
    "canvas",
    "panel",
    "panelRaised",
    "panelSunken",
    "textPrimary",
    "textSecondary",
    "textDisabled",
    "textInverse",
    "borderFocus",
    "accentText",
    "accentTextStrong",
    "accentTextMuted",
    "accentSurface",
    "accentSurfaceHover",
    "accentSurfaceActive",
    "accentSurfaceSubtle",
    "accentSurfaceSunken",
    "onAccentSurface",
    "onAccentSurfaceHover",
    "onAccentSurfaceActive",
    "onAccentText",
    "success",
    "warning",
    "danger",
    "info",
    "selectionBorder",
    "guideLine",
    "guideMeasurement",
)

#: Значения по темам. Тема выбирается на клиенте, поэтому контраст
#: проверяется по обеим сразу.
THEMES: dict[str, dict[str, str]] = {
    'light': {"appBg": "#E4E6E9", "canvas": "#F7F8F9", "panel": "#FFFFFF", "panelRaised": "#FFFFFF", "panelSunken": "#F0F1F3", "textPrimary": "#1A1C1E", "textSecondary": "#5B6169", "textDisabled": "#7A818B", "textInverse": "#FFFFFF", "borderFocus": "#7E5A12", "accentText": "#7E5A12", "accentTextStrong": "#6B4E0F", "accentTextMuted": "#8A6516", "accentSurface": "#D9A441", "accentSurfaceHover": "#E0AE4E", "accentSurfaceActive": "#C9962E", "accentSurfaceSubtle": "#F5E6C4", "accentSurfaceSunken": "#EFE0BC", "onAccentSurface": "#1A1C1E", "onAccentSurfaceHover": "#1A1C1E", "onAccentSurfaceActive": "#14161A", "onAccentText": "#F7F8F9", "success": "#3F6B33", "warning": "#8A652D", "danger": "#A4503C", "info": "#3F5A70", "selectionBorder": "#7E5A12", "guideLine": "#C9962E", "guideMeasurement": "#1A1C1E"},
    'dark': {"appBg": "#0A0B0D", "canvas": "#15171A", "panel": "#1F2226", "panelRaised": "#24272B", "panelSunken": "#0E0F11", "textPrimary": "#E8EAED", "textSecondary": "#A8AEB8", "textDisabled": "#6B717B", "textInverse": "#0E0F11", "borderFocus": "#D9A441", "accentText": "#E0B85C", "accentTextStrong": "#EFC978", "accentTextMuted": "#D4A94A", "accentSurface": "#C9962E", "accentSurfaceHover": "#D9A441", "accentSurfaceActive": "#B8862A", "accentSurfaceSubtle": "#2E2513", "accentSurfaceSunken": "#241D0F", "onAccentSurface": "#1A1C1E", "onAccentSurfaceHover": "#1A1C1E", "onAccentSurfaceActive": "#1A1C1E", "onAccentText": "#1A1C1E", "success": "#7FA86F", "warning": "#D9A441", "danger": "#E08573", "info": "#7FA3C4", "selectionBorder": "#D9A441", "guideLine": "#D9A441", "guideMeasurement": "#E8EAED"},
}
