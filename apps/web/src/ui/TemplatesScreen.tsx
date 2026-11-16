/**
 * Шаблоны страниц и блоков (этап 2).
 *
 * Зачем отдельный экран: шаблон — это снимок, который переживает
 * правки страницы. Человек приходит сюда, чтобы сохранить удачное
 * решение и повторить его, а не чтобы редактировать содержимое.
 *
 * Страницы создаются здесь же: шаблон применяется обычным созданием
 * страницы, поэтому лимиты тарифа и права проверяются в одном месте.
 * Блок вставляется в редакторе — экран не знает, на какую страницу и
 * в какое место его положить.
 */

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import { api } from './api';
import type { Block, Project } from './project';
import {
  templatesApi,
  type TemplateKind,
  type TemplateSummary,
} from './templates';

type Props = {
  projectId: string;
  projectName: string;
  onBack: () => void;
};

type Notice = { kind: 'ok' | 'bad'; text: string };

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message || `Ошибка ${error.status}`;
  }
  return error instanceof Error ? error.message : 'Не получилось. Попробуйте ещё раз.';
}

/** «1 блок», «2 блока», «5 блоков». */
function blocksLabel(count: number): string {
  const tail = count % 100;
  const last = count % 10;
  if (tail >= 11 && tail <= 14) return `${count} блоков`;
  if (last === 1) return `${count} блок`;
  if (last >= 2 && last <= 4) return `${count} блока`;
  return `${count} блоков`;
}

const KIND_LABELS: Record<TemplateKind, string> = {
  page: 'Страница',
  block: 'Блок',
};

export function TemplatesScreen({ projectId, projectName, onBack }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [limit, setLimit] = useState(50);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [kind, setKind] = useState<TemplateKind>('page');
  const [name, setName] = useState('');
  const [pageId, setPageId] = useState('');
  const [blockId, setBlockId] = useState('');
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [listing, fresh] = await Promise.all([
      templatesApi.list(projectId),
      api.getProject(projectId),
    ]);
    setTemplates(listing.templates);
    setLimit(listing.limit);
    setProject(fresh);
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void load()
      .catch((e) => {
        if (!cancelled) setNotice({ kind: 'bad', text: explain(e) });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  /*
   * Блоки выбранной страницы. Главная лежит в project.tree, остальные
   * приходят отдельным запросом: тянуть все страницы проекта ради
   * выпадающего списка значило бы открыть их деревья целиком.
   */
  useEffect(() => {
    if (kind !== 'block' || project === null) {
      setBlocks([]);
      return;
    }
    if (pageId === '') {
      setBlocks(project.tree.blocks);
      return;
    }
    let cancelled = false;
    void api
      .getPage(projectId, pageId)
      .then((page) => {
        if (!cancelled) setBlocks(page.tree.blocks);
      })
      .catch(() => {
        if (!cancelled) setBlocks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [kind, pageId, project, projectId]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    const clean = name.trim();
    if (!clean || busy !== null) return;
    if (kind === 'block' && !blockId) {
      setNotice({ kind: 'bad', text: 'Выберите блок, который сохранить.' });
      return;
    }
    setBusy('create');
    setNotice(null);
    try {
      await templatesApi.create(projectId, {
        name: clean,
        kind,
        ...(pageId ? { page: pageId } : {}),
        ...(kind === 'block' ? { block: blockId } : {}),
      });
      setName('');
      setBlockId('');
      setNotice({ kind: 'ok', text: `Шаблон «${clean}» сохранён.` });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const applyPage = async (template: TemplateSummary) => {
    if (busy !== null) return;
    setBusy(`apply-${template.id}`);
    setNotice(null);
    try {
      const detail = await templatesApi.get(projectId, template.id);
      // Дерево проверяется на сервере теми же правилами, что и обычное
      // сохранение: шаблон не может пронести в страницу невалидный блок.
      const page = await api.createPage(projectId, template.name, undefined, detail.tree);
      setNotice({
        kind: 'ok',
        text: `Страница «${page.title}» создана: /${page.slug}/. Наполнить её можно в редакторе.`,
      });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const remove = async (template: TemplateSummary) => {
    if (busy !== null) return;
    // Удаление необратимо, поэтому первый клик только спрашивает.
    if (confirmingId !== template.id) {
      setConfirmingId(template.id);
      return;
    }
    setBusy(`delete-${template.id}`);
    setNotice(null);
    try {
      await templatesApi.remove(projectId, template.id);
      setConfirmingId(null);
      setNotice({ kind: 'ok', text: `Шаблон «${template.name}» удалён.` });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="data tpl">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Шаблоны: {projectName}</h1>
      </header>

      {notice ? (
        <p
          className={notice.kind === 'bad' ? 'data__error' : 'vers__ok'}
          role={notice.kind === 'bad' ? 'alert' : 'status'}
        >
          {notice.text}
        </p>
      ) : null}

      <section className="data__panel" data-screen="templates-create">
        <h2 className="data__panel-title">Сохранить как шаблон</h2>
        <p className="props__note">
          Шаблон — снимок: последующие правки страницы его не меняют.
          Хранится в этом проекте, потому что блоки могут ссылаться на его
          источники данных и медиатеку.
        </p>
        <form className="tpl__form" onSubmit={(e) => void create(e)}>
          <label className="prop">
            <span className="prop__label">Название</span>
            <input
              className="prop__input"
              value={name}
              maxLength={120}
              placeholder="Например, Лендинг услуги"
              onChange={(e) => setName(e.target.value)}
              disabled={busy !== null}
            />
          </label>

          <label className="prop">
            <span className="prop__label">Что сохранить</span>
            <select
              className="prop__input"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as TemplateKind);
                setBlockId('');
              }}
              disabled={busy !== null}
            >
              <option value="page">Страницу целиком</option>
              <option value="block">Один блок</option>
            </select>
          </label>

          <label className="prop">
            <span className="prop__label">
              {kind === 'block' ? 'Откуда взять блок' : 'Какую страницу'}
            </span>
            <select
              className="prop__input"
              value={pageId}
              onChange={(e) => {
                setPageId(e.target.value);
                setBlockId('');
              }}
              disabled={busy !== null || project === null}
            >
              <option value="">
                {project ? `${project.name} — главная` : 'Главная'}
              </option>
              {(project?.pages ?? []).map((page) => (
                <option key={page.id} value={page.id}>
                  {page.title}
                </option>
              ))}
            </select>
          </label>

          {kind === 'block' ? (
            <label className="prop">
              <span className="prop__label">Блок</span>
              <select
                className="prop__input"
                value={blockId}
                onChange={(e) => setBlockId(e.target.value)}
                disabled={busy !== null || blocks.length === 0}
              >
                <option value="">
                  {blocks.length === 0 ? 'На странице нет блоков' : 'Выберите блок'}
                </option>
                {blocks.map((block) => (
                  <option key={block.id} value={block.id}>
                    {block.label || block.module} · {block.module}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <div className="data__actions tpl__submit">
            <button
              type="submit"
              className="btn btn--primary"
              disabled={
                busy !== null ||
                !name.trim() ||
                (kind === 'block' && !blockId)
              }
            >
              {busy === 'create' ? 'Сохраняем…' : 'Сохранить шаблон'}
            </button>
            <span className="props__note">
              {templates.length} из {limit}
            </span>
          </div>
        </form>
      </section>

      <section className="data__panel" data-screen="templates-list">
        <h2 className="data__panel-title">Шаблоны проекта</h2>
        {loading ? (
          <p className="data__hint">Загружаем шаблоны…</p>
        ) : templates.length === 0 ? (
          <p className="props__note">
            Пока пусто. Сохраните страницу или блок, чтобы повторить решение
            на другой странице.
          </p>
        ) : (
          <ul className="tpl__list">
            {templates.map((template) => (
              <li key={template.id} className="tpl__row">
                <div className="tpl__text">
                  <b>{template.name}</b>
                  <span className="tpl__meta">
                    {KIND_LABELS[template.kind]}
                    {template.title ? ` · ${template.title}` : ''}
                    {template.kind === 'page'
                      ? ` · ${blocksLabel(template.blocks)}`
                      : template.module
                        ? ` · ${template.module}`
                        : ''}
                    {` · ${new Date(template.createdAt).toLocaleDateString('ru-RU')}`}
                  </span>
                  {template.kind === 'block' ? (
                    <span className="props__note">
                      Вставляется в редакторе: панель «Модули» → «Шаблоны».
                    </span>
                  ) : null}
                </div>
                <div className="tpl__actions">
                  {template.kind === 'page' ? (
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void applyPage(template)}
                      disabled={busy !== null}
                    >
                      {busy === `apply-${template.id}`
                        ? 'Создаём…'
                        : 'Создать страницу'}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={
                      confirmingId === template.id
                        ? 'btn btn--danger'
                        : 'btn btn--ghost'
                    }
                    onClick={() => void remove(template)}
                    disabled={busy !== null}
                  >
                    {busy === `delete-${template.id}`
                      ? 'Удаляем…'
                      : confirmingId === template.id
                        ? 'Точно удалить?'
                        : 'Удалить'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
