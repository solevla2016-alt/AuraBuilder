"""Провайдеры помощника: локальные правила и YandexGPT.

Провайдеров два, и это не временная заглушка. Локальные правила дают
полезный ответ без сети и без ключа, поэтому пакет остаётся рабочим
офлайн и в self-hosted (ТЗ п.16.4). YandexGPT подключается
переменными окружения и даёт развёрнутые формулировки, но не является
условием работы помощника.

Наружу уходит только описание, которое человек ввёл сам, и сводка
проекта (число страниц и записей). Содержимое страниц и данные
клиентов в промпт не попадают — это важнее качества ответа.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from projects.module_registry import MODULES_BY_ID

from .actions import Action

logger = logging.getLogger(__name__)

#: Таймаут одного обращения к внешней модели. Достаточно долго для
#: длинного ответа и достаточно коротко, чтобы человек не решил, что
#: кнопка не работает.
TIMEOUT = 25

PROVIDER_TITLES = {
    'local': 'Локальные правила',
    'yandex': 'YandexGPT',
}


class ProviderError(RuntimeError):
    """Провайдер недоступен или ответил не тем, что ожидалось."""


class AssistantResult:
    """Ответ помощника в форме, общей для обоих провайдеров."""

    __slots__ = ('summary', 'items', 'provider', 'tokens')

    def __init__(
        self,
        summary: str,
        items: list[dict],
        provider: str,
        tokens: int = 0,
    ) -> None:
        self.summary = summary
        self.items = items
        self.provider = provider
        self.tokens = tokens

    def as_dict(self) -> dict:
        return {
            'summary': self.summary,
            'items': self.items,
            'provider': self.provider,
            'tokens': self.tokens,
        }


def provider_code() -> str:
    """Какой провайдер выбран настройками.

    `auto` означает «YandexGPT, если он настроен, иначе локальные
    правила». Так стенд и self-hosted не требуют ключа, а облако с
    ключом не требует отдельного переключателя.
    """
    configured = (settings.AI_PROVIDER or 'auto').lower()
    if configured == 'auto':
        ready = bool(
            settings.YANDEX_GPT_API_KEY and settings.YANDEX_GPT_FOLDER_ID
        )
        return 'yandex' if ready else 'local'
    return configured


def provider_info() -> dict:
    """Провайдер и его готовность для экрана помощника.

    Готовность отдаётся отдельно от кода: если выбран YandexGPT без
    ключа, экран должен сказать об этом до нажатия кнопки, а не
    показать 502 после.
    """
    code = provider_code()
    ready = code == 'local' or bool(
        settings.YANDEX_GPT_API_KEY and settings.YANDEX_GPT_FOLDER_ID
    )
    if code == 'local':
        detail = (
            'Внешняя модель не подключена: структура строится локальными '
            'правилами. Это работает офлайн и без ключа.'
        )
    elif ready:
        detail = (
            'Ответы готовит YandexGPT. На сервер отправляется только '
            'ваше описание и сводка проекта, без содержимого страниц.'
        )
    else:
        detail = (
            'Выбран YandexGPT, но ключ не задан. Укажите '
            'YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID или верните '
            'AI_PROVIDER=local.'
        )
    return {
        'code': code,
        'title': PROVIDER_TITLES.get(code, code),
        'external': code == 'yandex',
        'ready': ready,
        'detail': detail,
    }


def get_provider():
    """Экземпляр выбранного провайдера.

    Ошибка конфигурации — исключение, а не тихий переход на локальные
    правила: иначе владелец облака решил бы, что платит за YandexGPT,
    хотя получает шаблонные подсказки.
    """
    code = provider_code()
    if code == 'local':
        return LocalProvider()
    if code == 'yandex':
        if not settings.YANDEX_GPT_API_KEY or not settings.YANDEX_GPT_FOLDER_ID:
            raise ProviderError(
                'YandexGPT выбран, но не настроен: задайте '
                'YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID.'
            )
        return YandexGptProvider()
    raise ProviderError(f'Неизвестный провайдер ИИ: {code!r}.')


# ---------------------------------------------------------------------
#  Локальные правила
# ---------------------------------------------------------------------


def _outline_item(module: str, detail: str) -> dict:
    meta = MODULES_BY_ID.get(module)
    return {
        'title': meta.name if meta else module,
        'module': module,
        'detail': detail,
    }


def _field(
    key: str,
    label: str,
    field_type: str,
    required: bool,
    detail: str,
) -> dict:
    return {
        'key': key,
        'label': label,
        'type': field_type,
        'required': required,
        'detail': detail,
    }


class LocalProvider:
    """Ответы по правилам: ключевые слова в описании выбирают модули.

    Это не попытка заменить модель, а нижняя граница качества: даже
    без ключа человек получает структуру, которую можно править, а не
    пустой экран. Формулировки намеренно короткие и проверяемые.
    """

    name = 'local'

    def generate(
        self,
        action: Action,
        description: str,
        context: dict,
    ) -> AssistantResult:
        handlers = {
            'page_outline': self._outline,
            'data_schema': self._schema,
            'project_review': self._review,
        }
        handler = handlers.get(action.code)
        if handler is None:
            raise ProviderError(f'Действие {action.code!r} не поддержано.')
        summary, items = handler(description, context)
        return AssistantResult(summary, items, self.name)

    # -- План страницы -------------------------------------------------

    def _outline(self, description: str, context: dict) -> tuple[str, list[dict]]:
        text = description.lower()
        items = [
            _outline_item(
                'section.hero',
                'Первый экран отвечает на вопрос «куда я попал» и ведёт '
                'к главному действию.',
            ),
        ]
        rules = (
            (
                ('преимущ', 'выгод', 'почему мы', 'особенн', 'ценност'),
                'section.feature',
                'Преимущества объясняют выбор до того, как человек '
                'увидит цену.',
            ),
            (
                ('цен', 'тариф', 'стоим', 'прайс', 'прайс-лист'),
                'promo.pricing',
                'Тарифы рядом: без цены посетитель уходит искать её '
                'в другом месте.',
            ),
            (
                ('каталог', 'товар', 'магазин', 'ассортимент', 'услуг',
                 'портфолио', 'проект'),
                'data.collection',
                'Коллекция показывает то, что можно выбрать или '
                'заказать, и питается из источника данных.',
            ),
            (
                ('этап', 'шаг', 'процесс', 'как работа', 'как мы работаем'),
                'section.steps',
                'Шаги снимают тревогу «а что дальше» и показывают '
                'порядок работы.',
            ),
            (
                ('отзыв', 'клиент', 'кейс', 'результат'),
                'trust.review',
                'Отзывы — доказательство вместо обещаний.',
            ),
            (
                ('вопрос', 'faq', 'частые'),
                'section.accordion',
                'Частые вопросы закрывают возражения без переписки.',
            ),
            (
                ('фото', 'галере', 'изображен', 'работы'),
                'section.gallery',
                'Галерея показывает результат, когда словами его '
                'не передать.',
            ),
            (
                ('команд', 'сотрудник', 'о нас', 'эксперт', 'мастер'),
                'section.split',
                'Блок о команде отвечает «кто эти люди» и повышает '
                'доверие.',
            ),
            (
                ('контакт', 'связ', 'заявк', 'форма', 'записаться',
                 'оставить'),
                'action.form',
                'Форма заявки — финальное действие страницы; она '
                'создаёт запись в источнике данных.',
            ),
        )
        for keywords, module, detail in rules:
            if any(word in text for word in keywords):
                items.append(_outline_item(module, detail))

        if len(items) == 1:
            items.extend([
                _outline_item(
                    'section.feature',
                    'Без преимуществ первый экран остаётся лозунгом: '
                    'добавьте 3–4 причины выбрать вас.',
                ),
                _outline_item(
                    'text.paragraph',
                    'Короткий текст связывает первый экран с '
                    'остальными секциями.',
                ),
            ])

        items.append(_outline_item(
            'section.footer',
            'Подвал закрывает страницу: контакты, реквизиты и ссылки '
            'на документы.',
        ))
        summary = (
            f'План страницы: {len(items)} секций. Сверху вниз — от '
            f'первого экрана к заявке; названия модулей можно найти '
            f'в палитре «Модули».'
        )
        return summary, items

    # -- Схема данных --------------------------------------------------

    def _schema(self, description: str, context: dict) -> tuple[str, list[dict]]:
        text = description.lower()
        if any(word in text for word in ('каталог', 'товар', 'магазин',
                                         'мебел', 'ассортимент', 'склад')):
            items = [
                _field('name', 'Название', 'text', True,
                       'По нему запись ищут в списке и поиске.'),
                _field('description', 'Описание', 'text', False,
                       'Короткое описание для карточки.'),
                _field('price', 'Цена', 'number', True,
                       'Число без знака валюты: формат задаётся на странице.'),
                _field('category', 'Категория', 'text', False,
                       'Текст, а не отдельный справочник: на старте '
                       'категорий немного.'),
                _field('image', 'Фотография', 'image', False,
                       'В медиатеке проекта, а не внешней ссылкой.'),
                _field('stock', 'Остаток', 'number', False,
                       'Ноль означает «нет в наличии» и скрывает кнопку.'),
                _field('published', 'Опубликовано', 'boolean', True,
                       'Черновик не должен попадать на страницу.'),
            ]
            summary = ('Схема каталога: 7 полей. Цена и остаток — числа, '
                       'чтобы сортировка и фильтры работали без разбора '
                       'текста.')
        elif any(word in text for word in ('заявк', 'заказ', 'клиент',
                                           'записаться', 'обратн')):
            items = [
                _field('name', 'Имя', 'text', True,
                       'Без имени заявку не к кому адресовать.'),
                _field('phone', 'Телефон', 'text', True,
                       'Текст, а не число: ведущий плюс и скобки — часть '
                       'записи.'),
                _field('email', 'Почта', 'text', False,
                       'Необязательна, если основной канал — телефон.'),
                _field('message', 'Комментарий', 'text', False,
                       'Свободный текст с деталями заказа.'),
                _field('consent', 'Согласие на обработку', 'boolean', True,
                       'Требование 152-ФЗ: без согласия заявку '
                       'обрабатывать нельзя.'),
                _field('status', 'Статус', 'text', True,
                       'Новая, в работе, закрыта — чтобы не терять '
                       'обращения.'),
            ]
            summary = ('Схема заявки: 6 полей. Согласие хранится отдельным '
                       'полем, а не подразумевается.')
        elif any(word in text for word in ('отзыв', 'оценк', 'рейтинг')):
            items = [
                _field('author', 'Автор', 'text', True,
                       'Имя того, кто оставил отзыв.'),
                _field('text', 'Текст отзыва', 'text', True,
                       'Дословно, без редактуры.'),
                _field('rating', 'Оценка', 'number', False,
                       'От 1 до 5; ноль — оценку не ставили.'),
                _field('review_date', 'Дата', 'date', False,
                       'Дата отзыва, а не дата импорта.'),
                _field('published', 'Опубликован', 'boolean', True,
                       'Проверенный отзыв попадает на сайт только после '
                       'включения.'),
            ]
            summary = 'Схема отзыва: 5 полей. Публикация отделена от записи.'
        elif any(word in text for word in ('статья', 'блог', 'новост',
                                           'материал')):
            items = [
                _field('title', 'Заголовок', 'text', True,
                       'Главный текст ссылки и карточки.'),
                _field('slug', 'Адрес', 'text', True,
                       'Латиница и дефисы: попадает в URL.'),
                _field('excerpt', 'Лид', 'text', False,
                       'Одно-два предложения для списка статей.'),
                _field('body', 'Текст', 'text', True,
                       'Основное содержимое материала.'),
                _field('cover', 'Обложка', 'image', False,
                       'Картинка для карточки и соцсетей.'),
                _field('published_at', 'Дата публикации', 'date', False,
                       'Отдельно от даты создания записи.'),
                _field('published', 'Опубликовано', 'boolean', True,
                       'Черновик не виден на сайте.'),
            ]
            summary = ('Схема материала: 7 полей. Дата публикации — '
                       'отдельная от служебной даты записи.')
        else:
            items = [
                _field('title', 'Название', 'text', True,
                       'Короткое имя записи.'),
                _field('description', 'Описание', 'text', False,
                       'Подробности, если они нужны.'),
                _field('status', 'Статус', 'text', False,
                       'Этап, на котором находится запись.'),
            ]
            summary = ('Универсальная схема: 3 поля. Уточните задачу — '
                       'помощник добавит поля под неё.')
        return summary, items

    # -- Разбор проекта ------------------------------------------------

    def _review(self, description: str, context: dict) -> tuple[str, list[dict]]:
        name = context.get('project') or 'Проект'
        pages = int(context.get('pages') or 1)
        records = int(context.get('records') or 0)
        published = bool(context.get('published'))
        items: list[dict] = []

        if not published:
            items.append({
                'title': 'Опубликуйте сайт',
                'detail': 'Пока сайт не опубликован, его не видел ни один '
                          'посетитель: сначала проверьте страницу, затем '
                          'нажмите «Опубликовать».',
            })
        if pages < 2:
            items.append({
                'title': 'Добавьте вторую страницу',
                'detail': 'Одной главной хватает для визитки, но не для '
                          'поиска: страница «О нас» или «Контакты» даёт '
                          'внутренние ссылки.',
            })
        if records == 0:
            items.append({
                'title': 'Заведите источник данных',
                'detail': 'Заявки, каталог и отзывы хранятся в узлах '
                          'данных. Без источника форма сохраняет в никуда.',
            })
        else:
            items.append({
                'title': 'Покажите данные на странице',
                'detail': f'В проекте уже {records} записей. Добавьте '
                          f'коллекцию или список, иначе данные видны '
                          f'только в редакторе.',
                'module': 'data.collection',
            })
        items.append({
            'title': 'Проверьте микроразметку',
            'detail': 'Модуль seo.schema помогает поиску понять страницу. '
                      'Это дешевле, чем переделывать после запуска.',
            'module': 'seo.schema',
        })

        if published:
            summary = (f'{name}: сайт опубликован, страниц — {pages}, '
                       f'записей — {records}. Дальше стоит укрепить '
                       f'содержание, а не менять оформление.')
        else:
            summary = (f'{name}: страниц — {pages}, записей — {records}, '
                       f'публикации ещё не было. Первый шаг — показать '
                       f'сайт людям.')
        return summary, items


# ---------------------------------------------------------------------
#  YandexGPT
# ---------------------------------------------------------------------


class YandexGptProvider:
    """YandexGPT через Foundation Models API.

    Запрос собирается вручную через urllib: ради одного POST тянуть
    HTTP-библиотеку в пакет незачем, а стандартная библиотека уже
    проверена лицензионным гейтом. Ответ модели ожидается в JSON —
    если модель ответила текстом, он показывается как есть, а не
    превращается в пустой экран.
    """

    name = 'yandex'
    endpoint = (
        'https://llm.api.cloud.yandex.net/foundationModels/v1/completion'
    )

    def __init__(
        self,
        api_key: str | None = None,
        folder_id: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.YANDEX_GPT_API_KEY
        self.folder_id = folder_id or settings.YANDEX_GPT_FOLDER_ID
        self.model = model or settings.YANDEX_GPT_MODEL

    def generate(
        self,
        action: Action,
        description: str,
        context: dict,
    ) -> AssistantResult:
        payload = {
            'modelUri': f'gpt://{self.folder_id}/{self.model}/latest',
            'completionOptions': {
                'stream': False,
                'temperature': 0.2,
                'maxTokens': 1500,
            },
            'messages': self.messages(action, description, context),
        }
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method='POST',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Api-Key {self.api_key}',
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            logger.warning('YandexGPT ответил кодом %s', exc.code)
            raise ProviderError(
                'YandexGPT временно недоступен. Попробуйте позже: '
                'кредиты за неудачный запрос не списываются.'
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning('YandexGPT недоступен: %s', exc)
            raise ProviderError(
                'Не удалось связаться с YandexGPT. Проверьте сеть или '
                'вернитесь к локальным подсказкам.'
            ) from exc

        try:
            data = json.loads(raw)
            text = data['result']['alternatives'][0]['message']['text']
            tokens = int(data.get('result', {}).get('usage', {}).get(
                'totalTokens', 0,
            ))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning('Неожиданный ответ YandexGPT: %s', raw[:300])
            raise ProviderError(
                'YandexGPT ответил в неизвестном формате. Попробуйте '
                'ещё раз.'
            ) from exc

        summary, items = parse_model_text(text)
        return AssistantResult(summary, items, self.name, tokens)

    def messages(
        self,
        action: Action,
        description: str,
        context: dict,
    ) -> list[dict]:
        """Сообщения модели. Отдельный метод — его можно проверить без сети."""
        system = (
            'Ты помощник по структуре сайтов на платформе AuraBuilder. '
            'Отвечай только JSON-объектом без markdown и пояснений. '
            'Пиши по-русски. Не выдумывай модули и поля, которых нет '
            'в инструкции. Не сочиняй тексты для сайта: ты предлагаешь '
            'структуру, а не готовый контент.'
        )
        user = (
            f'{action.instruction}\n\n'
            f'Описание пользователя: {description or "не задано"}\n\n'
            f'Сводка проекта: {json.dumps(context, ensure_ascii=False)}'
        )
        return [
            {'role': 'system', 'text': system},
            {'role': 'user', 'text': user},
        ]


def parse_model_text(text: str) -> tuple[str, list[dict]]:
    """Разбирает ответ модели на сводку и элементы.

    Модель может обернуть JSON в ```json или добавить фразу до него.
    Поэтому ищутся крайние фигурные скобки, а не первая строка. Если
    JSON не разобрался, весь текст становится сводкой: показать
    полезный ответ без структуры лучше, чем ошибку.
    """
    raw = (text or '').strip()
    start = raw.find('{')
    end = raw.rfind('}')
    if start == -1 or end <= start:
        return raw, []

    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return raw, []
    if not isinstance(data, dict):
        return raw, []

    summary = str(data.get('summary') or '').strip()
    items = _clean_items(data.get('items'))
    if not summary:
        summary = raw if not items else 'Готово.'
    return summary, items


def _clean_items(raw) -> list[dict]:
    """Оставляет только известные поля элемента.

    Лишние ключи от модели не должны попадать в API: интерфейс
    рендерит известные поля, а неизвестные молча теряются, и лучше
    отбросить их здесь, чем надеяться на дисциплину модели.
    """
    if not isinstance(raw, list):
        return []
    allowed = ('title', 'detail', 'module', 'key', 'label', 'type',
               'required')
    items: list[dict] = []
    for entry in raw[:12]:
        if not isinstance(entry, dict):
            continue
        item = {}
        for key in allowed:
            value = entry.get(key)
            if key == 'required':
                if isinstance(value, bool):
                    item[key] = value
            elif value is not None:
                item[key] = str(value).strip()
        if item.get('title') or item.get('label'):
            items.append(item)
    return items


__all__ = [
    'AssistantResult',
    'LocalProvider',
    'PROVIDER_TITLES',
    'ProviderError',
    'YandexGptProvider',
    'get_provider',
    'parse_model_text',
    'provider_code',
    'provider_info',
]
