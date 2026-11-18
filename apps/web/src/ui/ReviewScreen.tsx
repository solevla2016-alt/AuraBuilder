/**
 * Ревью-режим: замечания к блокам и согласование до публикации.
 *
 * Отдельный экран, а не панель на холсте: замечание — это работа с
 * содержанием, и человеку нужно видеть страницу целиком, а не только
 * выбранный блок. Комментарии не попадают в пакет: после публикации
 * сайт живёт без платформы.
 *
 * Действия не скрываются по роли: фронтенд не знает роль в проекте
 * (она живёт в Membership), а сервер отвечает 403 с понятным текстом.
 * Прятать кнопку значило бы дублировать матрицу прав и разойтись с ней.
 */

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Icon } from './icons';
import { ApiError } from './apiClient';
import { api } from './api';
import type { Block, Project, ReviewStatus } from './project';
import {
  reviewApi,
  type ReviewAction,
  type ReviewComment,
  type ReviewSummary,
} from './review';

type Props = {
  projectId: string;
  projectName: string;
  onBack: () => void;
};

type Notice = { kind: 'ok' | 'bad'; text: string };

const STATUS_LABELS: Record<ReviewStatus, string> = {
  draft: 'Черновик',
  pending: 'На согласовании',
  changes: 'Нужны правки',
  approved: 'Согласовано',
};

/** Кто может запросить ревью: всё, кроме уже отправленного. */
const canRequest = (status: ReviewStatus) => status !== 'pending';
/** Согласовать можно то, что ждёт решения. */
const canApprove = (status: ReviewStatus) =>
  status === 'pending' || status === 'changes';
/** Вернуть с замечаниями — только то, что на согласовании. */
const canReturn = (status: ReviewStatus) => status === 'pending';

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message || `Ошибка ${error.status}`;
  }
  return error instanceof Error ? error.message : 'Не получилось. Попробуйте ещё раз.';
}

function StatusBadge({ status }: { status: ReviewStatus }) {
  return (
    <span className={`review__badge review__badge--${status}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}

export function ReviewScreen({ projectId, projectName, onBack }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [comments, setComments] = useState<ReviewComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [filter, setFilter] = useState('all');
  const [composePage, setComposePage] = useState('main');
  const [composeBlock, setComposeBlock] = useState('');
  const [text, setText] = useState('');
  const [blocks, setBlocks] = useState<Record<string, Block[]>>({});
  const [showResolved, setShowResolved] = useState(false);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [fresh, state, listing] = await Promise.all([
      api.getProject(projectId),
      reviewApi.summary(projectId),
      reviewApi.comments(projectId, filter === 'all' ? undefined : filter),
    ]);
    setProject(fresh);
    setSummary(state);
    setComments(listing.comments);
  }, [projectId, filter]);

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
   * Блоки нужны дважды: для выбора при новом замечании и для подписи
   * «блок …» в списке. Главная уже есть в проекте, остальные страницы
   * догружаются по требованию: тянуть все деревья сразу незачем.
   */
  useEffect(() => {
    if (project === null) return;
    const keys = new Set<string>(comments.map((item) => item.page ?? 'main'));
    keys.add(composePage);
    for (const key of keys) {
      if (key === 'main') continue;
      if (blocks[key]) continue;
      void api
        .getPage(projectId, key)
        .then((page) => {
          setBlocks((current) => ({ ...current, [key]: page.tree.blocks }));
        })
        .catch(() => {
          // Страницу могли удалить: подпись блока останется его id.
        });
    }
  }, [blocks, comments, composePage, project, projectId]);

  const pageOptions = summary?.pages ?? [];
  const pageTitle = (key: string | null) =>
    key === null
      ? 'Главная'
      : pageOptions.find((page) => page.id === key)?.title ?? 'Страница';

  const blocksOf = (key: string): Block[] =>
    key === 'main' ? project?.tree.blocks ?? [] : blocks[key] ?? [];

  const blockTitle = (comment: ReviewComment) => {
    if (!comment.blockId) return '';
    const key = comment.page ?? 'main';
    const found = blocksOf(key).find((block) => block.id === comment.blockId);
    return found ? found.label || found.module : comment.blockId;
  };

  const act = async (action: ReviewAction, page?: string) => {
    if (busy !== null) return;
    setBusy(`review-${page ?? 'project'}`);
    setNotice(null);
    try {
      const fresh = await reviewApi.act(projectId, action, page);
      setSummary(fresh);
      const where = page ? 'Страница' : 'Проект';
      const done = action === 'request'
        ? 'отправлен на согласование.'
        : action === 'approve'
          ? 'согласован.'
          : 'возвращён с замечаниями.';
      setNotice({ kind: 'ok', text: `${where} ${done}` });
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const addComment = async (event: FormEvent) => {
    event.preventDefault();
    const clean = text.trim();
    if (!clean || busy !== null) return;
    setBusy('comment');
    setNotice(null);
    try {
      await reviewApi.addComment(projectId, {
        text: clean,
        ...(composePage === 'main' ? {} : { page: composePage }),
        ...(composeBlock ? { blockId: composeBlock } : {}),
      });
      setText('');
      setComposeBlock('');
      setNotice({ kind: 'ok', text: 'Замечание добавлено.' });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const toggleResolved = async (comment: ReviewComment) => {
    if (busy !== null) return;
    setBusy(`comment-${comment.id}`);
    setNotice(null);
    try {
      await reviewApi.resolve(projectId, comment.id, !comment.resolved);
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const removeComment = async (comment: ReviewComment) => {
    if (busy !== null) return;
    if (confirmingId !== comment.id) {
      setConfirmingId(comment.id);
      return;
    }
    setBusy(`comment-${comment.id}`);
    setNotice(null);
    try {
      await reviewApi.remove(projectId, comment.id);
      setConfirmingId(null);
      setNotice({ kind: 'ok', text: 'Замечание удалено.' });
      await load();
    } catch (e) {
      setNotice({ kind: 'bad', text: explain(e) });
    } finally {
      setBusy(null);
    }
  };

  const visible = [...comments]
    .filter((comment) => showResolved || !comment.resolved)
    .reverse();

  return (
    <main className="data review">
      <header className="data__top">
        <button type="button" className="btn btn--ghost" onClick={onBack}>
          <Icon name="back" />
          <span>В редактор</span>
        </button>
        <h1 className="data__title">Ревью: {projectName}</h1>
      </header>

      {notice ? (
        <p
          className={notice.kind === 'bad' ? 'data__error' : 'vers__ok'}
          role={notice.kind === 'bad' ? 'alert' : 'status'}
        >
          {notice.text}
        </p>
      ) : null}

      <section className="data__panel" data-screen="review-status">
        <div className="review__head">
          <div>
            <h2 className="data__panel-title">Согласование проекта</h2>
            <p className="props__note">
              Пока проект или любая страница на согласовании либо ждут
              правок, публикация блокируется. Обойти запрет может тот, кто
              публикует, — явным подтверждением на экране публикации.
            </p>
          </div>
          {summary ? <StatusBadge status={summary.status} /> : null}
        </div>

        {summary ? (
          <div className="data__actions review__actions">
            {canRequest(summary.status) ? (
              <button
                type="button"
                className="btn"
                onClick={() => void act('request')}
                disabled={busy !== null}
              >
                {busy === 'review-project' ? 'Отправляем…' : 'Запросить согласование'}
              </button>
            ) : null}
            {canApprove(summary.status) ? (
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void act('approve')}
                disabled={busy !== null}
              >
                Согласовать
              </button>
            ) : null}
            {canReturn(summary.status) ? (
              <button
                type="button"
                className="btn btn--danger"
                onClick={() => void act('changes')}
                disabled={busy !== null}
              >
                Вернуть с замечаниями
              </button>
            ) : null}
            <span className="props__note">
              Открытых замечаний: {summary.openComments}
              {summary.approvedBy
                ? ` · согласовал ${summary.approvedBy}`
                : ''}
            </span>
          </div>
        ) : null}
      </section>

      <section className="data__panel" data-screen="review-pages">
        <h2 className="data__panel-title">Страницы</h2>
        {loading ? (
          <p className="data__hint">Загружаем статусы…</p>
        ) : pageOptions.length === 0 ? (
          <p className="props__note">
            У проекта пока только главная страница — согласуйте её выше.
          </p>
        ) : (
          <ul className="tpl__list">
            {pageOptions.map((page) => (
              <li key={page.id} className="tpl__row">
                <div className="tpl__text">
                  <b>{page.title}</b>
                  <span className="tpl__meta">
                    /{page.slug}/ · замечаний: {page.openComments}
                    {page.approvedBy ? ` · согласовал ${page.approvedBy}` : ''}
                  </span>
                </div>
                <div className="tpl__actions">
                  <StatusBadge status={page.status} />
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => setFilter(page.id)}
                  >
                    Замечания
                  </button>
                  {canRequest(page.status) ? (
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void act('request', page.id)}
                      disabled={busy !== null}
                    >
                      На согласование
                    </button>
                  ) : null}
                  {canApprove(page.status) ? (
                    <button
                      type="button"
                      className="btn btn--primary"
                      onClick={() => void act('approve', page.id)}
                      disabled={busy !== null}
                    >
                      Согласовать
                    </button>
                  ) : null}
                  {canReturn(page.status) ? (
                    <button
                      type="button"
                      className="btn btn--danger"
                      onClick={() => void act('changes', page.id)}
                      disabled={busy !== null}
                    >
                      Вернуть
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="data__panel" data-screen="review-comment">
        <h2 className="data__panel-title">Новое замечание</h2>
        <form className="tpl__form" onSubmit={(e) => void addComment(e)}>
          <label className="prop">
            <span className="prop__label">Страница</span>
            <select
              className="prop__input"
              value={composePage}
              onChange={(e) => {
                setComposePage(e.target.value);
                setComposeBlock('');
              }}
              disabled={busy !== null}
            >
              <option value="main">Главная</option>
              {pageOptions.map((page) => (
                <option key={page.id} value={page.id}>
                  {page.title}
                </option>
              ))}
            </select>
          </label>

          <label className="prop">
            <span className="prop__label">Блок</span>
            <select
              className="prop__input"
              value={composeBlock}
              onChange={(e) => setComposeBlock(e.target.value)}
              disabled={busy !== null || blocksOf(composePage).length === 0}
            >
              <option value="">Вся страница</option>
              {blocksOf(composePage).map((block) => (
                <option key={block.id} value={block.id}>
                  {block.label || block.module} · {block.module}
                </option>
              ))}
            </select>
          </label>

          <label className="prop review__text">
            <span className="prop__label">Замечание</span>
            <textarea
              className="prop__input"
              value={text}
              maxLength={4000}
              rows={3}
              placeholder="Что исправить и почему"
              onChange={(e) => setText(e.target.value)}
              disabled={busy !== null}
            />
          </label>

          <div className="data__actions tpl__submit">
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy !== null || !text.trim()}
            >
              {busy === 'comment' ? 'Отправляем…' : 'Добавить замечание'}
            </button>
            <span className="props__note">
              Читать и комментировать может любой участник проекта.
            </span>
          </div>
        </form>
      </section>

      <section className="data__panel" data-screen="review-comments">
        <div className="review__head">
          <h2 className="data__panel-title">Замечания</h2>
          <div className="data__actions">
            <label className="prop">
              <span className="prop__label">Страница</span>
              <select
                className="prop__input"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                disabled={busy !== null}
              >
                <option value="all">Все страницы</option>
                <option value="main">Главная</option>
                {pageOptions.map((page) => (
                  <option key={page.id} value={page.id}>
                    {page.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="review__toggle">
              <input
                type="checkbox"
                checked={showResolved}
                onChange={(e) => setShowResolved(e.target.checked)}
              />
              <span>Показывать закрытые</span>
            </label>
          </div>
        </div>

        {loading ? (
          <p className="data__hint">Загружаем замечания…</p>
        ) : visible.length === 0 ? (
          <p className="props__note">
            {comments.length === 0
              ? 'Замечаний пока нет. Ревьюер увидит их здесь.'
              : 'Все замечания закрыты. Включите показ закрытых, чтобы прочитать их.'}
          </p>
        ) : (
          <ul className="review__list">
            {visible.map((comment) => (
              <li
                key={comment.id}
                className={comment.resolved ? 'review__item is-resolved' : 'review__item'}
              >
                <div className="review__meta">
                  <b>{comment.author || 'Участник'}</b>
                  <span>
                    {pageTitle(comment.page)}
                    {comment.blockId ? ` · блок ${blockTitle(comment)}` : ''}
                    {` · ${new Date(comment.createdAt).toLocaleString('ru-RU')}`}
                  </span>
                  {comment.resolved ? (
                    <span className="review__badge review__badge--approved">
                      Закрыто
                    </span>
                  ) : null}
                </div>
                <p className="review__body">{comment.text}</p>
                <div className="tpl__actions">
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => void toggleResolved(comment)}
                    disabled={busy !== null}
                  >
                    {comment.resolved ? 'Открыть заново' : 'Закрыть'}
                  </button>
                  <button
                    type="button"
                    className={
                      confirmingId === comment.id
                        ? 'btn btn--danger'
                        : 'btn btn--ghost'
                    }
                    onClick={() => void removeComment(comment)}
                    disabled={busy !== null}
                  >
                    {confirmingId === comment.id ? 'Точно удалить?' : 'Удалить'}
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
