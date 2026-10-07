/**
 * Список проектов (Dashboard V1, сетка — docs/UI-DECISIONS.md).
 *
 * Почему сетка, а не таблица: проектов у человека единицы, таблица
 * ради десятка строк выглядит как служебный отчёт, а карточки дают
 * место названию проекта, который всё равно приходится читать целиком.
 *
 * Три решения, которые видны только здесь:
 *
 * 1. Пустое состояние объясняет следующий шаг и содержит кнопку.
 *    Пустой экран без подсказки выглядит как поломка.
 *
 * 2. Удаление требует подтверждения с названием проекта внутри текста.
 *    Обычное «Вы уверены?» не защищает от промаха по кнопке рядом с
 *    «Открыть», а удалённый проект вместе с деревом не вернуть.
 *
 * 3. Роль в проекте показана на карточке, а не спрятана в меню: перед
 *    тем как открыть чужой проект на чтение, полезно видеть, что там
 *    можно только смотреть (ТЗ п.11.1).
 */

import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from './api';
import type { UserProfile } from './api';
import type { Project } from './project';
import { Icon } from './icons';

const ROLE_LABELS: Record<string, string> = {
  owner: 'Владелец',
  admin: 'Администратор',
  editor: 'Редактор',
  dev: 'Разработчик',
  viewer: 'Наблюдатель',
};

export function ProjectListScreen({
  user,
  onOpen,
  onSignOut,
}: {
  user: UserProfile;
  onOpen: (project: Project) => void;
  onSignOut: () => void;
}) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [pendingDelete, setPendingDelete] = useState<Project | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');

  const load = useCallback(async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить проекты.');
      setProjects([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Роль подгружается отдельно и не мешает показу списка: без неё
   * карточки всё равно полезны, а запрос на каждую карточку при
   * двадцати проектах дал бы двадцать обращений при открытии экрана.
   */
  useEffect(() => {
    if (!projects || projects.length === 0) return;
    let cancelled = false;
    void (async () => {
      const entries = await Promise.all(
        projects.map(async (p) => {
          try {
            const members = await api.members(p.id);
            const me = members.find((m) => m.username === user.username);
            return [p.id, me?.role ?? ''] as const;
          } catch {
            // Роль — справочная подпись: её отсутствие не должно
            // прятать проект или ронять весь экран.
            return [p.id, ''] as const;
          }
        }),
      );
      if (!cancelled) setRoles(Object.fromEntries(entries));
    })();
    return () => {
      cancelled = true;
    };
  }, [projects, user.username]);

  async function create() {
    const name = newName.trim();
    if (!name || busy) return;
    setBusy(true);
    try {
      const project = await api.createProject(name);
      setNewName('');
      setCreating(false);
      onOpen(project);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось создать проект.');
    } finally {
      setBusy(false);
    }
  }

  async function rename(project: Project, name: string) {
    const clean = name.trim();
    if (!clean || clean === project.name) return;
    try {
      await api.renameProject(project.id, clean);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось переименовать проект.');
    }
  }

  async function remove(project: Project) {
    setBusy(true);
    try {
      await api.deleteProject(project.id);
      setPendingDelete(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось удалить проект.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="dash">
      <header className="dash__top">
        <div className="dash__brand">
          <span className="dash__mark" aria-hidden="true" />
          <div>
            <h1 className="dash__title">Проекты</h1>
            <p className="dash__user">{user.email || user.username}</p>
          </div>
        </div>
        <button type="button" className="btn btn--ghost" onClick={onSignOut}>
          Выйти
        </button>
      </header>

      <section className="dash__toolbar">
        {creating ? (
          <div className="dash__create">
            <input
              className="dash__input"
              placeholder="Название проекта"
              value={newName}
              maxLength={200}
              autoFocus
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void create();
                if (e.key === 'Escape') setCreating(false);
              }}
            />
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || !newName.trim()}
              onClick={() => void create()}
            >
              Создать
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setCreating(false)}>
              Отмена
            </button>
          </div>
        ) : (
          <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>
            <Icon name="plus" />
            <span>Новый проект</span>
          </button>
        )}
      </section>

      {error ? (
        <p className="dash__error" role="alert">
          {error}
        </p>
      ) : null}

      {projects === null ? (
        <p className="dash__hint">Загружаем проекты…</p>
      ) : projects.length === 0 ? (
        <section className="dash__empty">
          <h2>Проектов пока нет</h2>
          <p>
            Создайте первый проект: в нём появятся холст, палитра модулей и контекстная
            панель настроек.
          </p>
          <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>
            Создать проект
          </button>
        </section>
      ) : (
        <ul className="dash__grid">
          {projects.map((project) => (
            // Идентификатор и имя лежат в разметке: автопроверка ищет карточку
      // по data-name, а не по тексту внутри — при одинаковых именах
      // текстовый поиск попадал не в ту карточку.
      <li
        key={project.id}
        className="dash__card"
        data-project={project.id}
        data-name={project.name}
      >
              <button
                type="button"
                className="dash__open"
                onClick={() => onOpen(project)}
              >
                <span className="dash__card-name">{project.name}</span>
                <span className="dash__card-meta">
                  {ROLE_LABELS[roles[project.id] ?? ''] ?? 'Участник'}
                  {' · '}
                  {formatDate(project.updatedAt)}
                </span>
                <span className="dash__card-blocks">
                  {project.tree?.blocks?.length ?? 0} блоков
                </span>
              </button>

              <div className="dash__card-actions">
                {renamingId === project.id ? (
                  /*
                   * Переименование делается полем в карточке, а не через
                   * window.prompt: системный диалог не под��ается под
                   * тему, не переводится и в автопроверках блокирует
                   * страницу до ответа.
                   */
                  <form
                    className="dash__rename"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void rename(project, renameDraft);
                      setRenamingId(null);
                    }}
                  >
                    <input
                      className="dash__rename-input"
                      aria-label="Новое название проекта"
                      value={renameDraft}
                      maxLength={200}
                      autoFocus
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') setRenamingId(null);
                      }}
                    />
                    <button type="submit" className="btn btn--primary">
                      Сохранить
                    </button>
                  </form>
                ) : (
                  <>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      title="Переименовать"
                      onClick={() => {
                        setRenamingId(project.id);
                        setRenameDraft(project.name);
                      }}
                    >
                      <Icon name="settings" size={14} />
                      <span>Имя</span>
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      title="Удалить"
                      onClick={() => setPendingDelete(project)}
                    >
                      <Icon name="close" size={14} />
                      <span>Удалить</span>
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {pendingDelete ? (
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="del-title">
          <div className="modal__card">
            <h2 id="del-title" className="modal__title">
              Удалить проект?
            </h2>
            <p className="modal__text">
              Проект «{pendingDelete.name}» и его страница будут удалены безвозвратно.
              Отменить это нельзя.
            </p>
            <div className="modal__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setPendingDelete(null)}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn btn--primary"
                disabled={busy}
                onClick={() => void remove(pendingDelete)}
              >
                Удалить
              </button>
            </div>
          </div>
        </div>
      ) : null}

    </main>
  );
}

/** «3 окт 2026, 14:05» — коротко и без локали по умолчанию. */
function formatDate(value: string | undefined): string {
  if (!value) return 'дата неизвестна';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'дата неизвестна';
  const pad = (n: number) => String(n).padStart(2, '0');
  const months = [
    'янв', 'фев', 'мар', 'апр', 'мая', 'июн',
    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
  ];
  return `${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}, ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}