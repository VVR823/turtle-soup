'use client';

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { decodeFeedbackPage, decodeFeedbackReview, feedbackNeedsManualCorrection, FeedbackContractError, type Feedback, type FeedbackStatus } from '@/lib/feedback-contract';
import AgentReviewPanel from '@/components/AgentReviewPanel';
import MetricsPanel from '@/components/MetricsPanel';

function displayClaim(value: string): string {
  return value.trim() ? value : '（仅空白，需人工核对）';
}

const ADMIN_TOKEN_KEY = 'turtle_admin_token';
const ADMIN_TOKEN_EVENT = 'turtle-admin-token-changed';
function savedAdminToken(): string {
  if (typeof window === 'undefined') return '';
  try { return localStorage.getItem(ADMIN_TOKEN_KEY) || ''; } catch { return ''; }
}
function subscribeAdminToken(listener: () => void): () => void {
  window.addEventListener('storage', listener); window.addEventListener(ADMIN_TOKEN_EVENT, listener);
  return () => { window.removeEventListener('storage', listener); window.removeEventListener(ADMIN_TOKEN_EVENT, listener); };
}
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE !== undefined
    ? process.env.NEXT_PUBLIC_API_BASE
    : 'http://localhost:8000';

function fmtTime(ts: string): string {
  try {
    return new Date(ts).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
  } catch {
    return ts;
  }
}

const STATUS_OPTIONS: { value: FeedbackStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
];

export default function AdminFeedbackPage() {
  const token = useSyncExternalStore(subscribeAdminToken, savedAdminToken, () => '');
  const [inputToken, setInputToken] = useState('');
  const needToken = !token;
  const [feedbacks, setFeedbacks] = useState<Feedback[]>([]);
  const [loadedToken, setLoadedToken] = useState('');
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const activeRequest = useRef<AbortController | null>(null);
  const activeReview = useRef<AbortController | null>(null);
  const requestEpoch = useRef(0);
  const [error, setError] = useState('');
  const [soupFilter, setSoupFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<FeedbackStatus | ''>('');
  const [tasksOpen, setTasksOpen] = useState(false);

  function load(t: string, cursor: string | null = null): Promise<void> {
    activeRequest.current?.abort();
    activeReview.current?.abort();
    requestEpoch.current++;
    const controller = new AbortController(); activeRequest.current = controller;
    const current = () => activeRequest.current === controller && !controller.signal.aborted && savedAdminToken() === t;
    const query = cursor === null ? '' : `?cursor=${encodeURIComponent(cursor)}`;
    return fetch(`${API_BASE}/api/feedback/admin${query}`, {
        headers: { 'X-Admin-Token': t },
        signal: controller.signal,
      }).then(async res => {
      if (!current()) return;
      if (res.status === 401) {
        localStorage.removeItem(ADMIN_TOKEN_KEY);
        window.dispatchEvent(new Event(ADMIN_TOKEN_EVENT));
        setError('管理口令错误，请重新输入');
        return;
      }
      if (!res.ok) {
        setError(`加载失败（${res.status}）`);
        return;
      }
      const data = decodeFeedbackPage(await res.json());
      if (!current()) return;
      setFeedbacks(previous => {
        if (cursor === null) return data.feedbacks;
        const combined = new Map(previous.map(item => [item.id, item]));
        for (const item of data.feedbacks) {
          if (!combined.has(item.id) || combined.get(item.id)!.rowVersion <= item.rowVersion) combined.set(item.id, item);
        }
        return [...combined.values()];
      });
      setTotal(data.totalInRange); setNextCursor(data.nextCursor);
      setLoadedToken(t);
      setError('');
    }).catch(error => {
      if (current()) setError(error instanceof FeedbackContractError ? error.message : '网络错误，请确认后端已启动');
    }).finally(() => {
      if (current()) { setLoading(false); setReviewingId(null); }
    });
  }

  useEffect(() => {
    if (token) void load(token);
    return () => { activeRequest.current?.abort(); activeReview.current?.abort(); };
  }, [token]);

  function submitToken() {
    const v = inputToken.trim();
    if (!v) return;
    localStorage.setItem(ADMIN_TOKEN_KEY, v);
    setLoading(true); setError('');
    window.dispatchEvent(new Event(ADMIN_TOKEN_EVENT));
  }

  async function review(id: string, action: 'approve' | 'reject') {
    if (!token || loadedToken !== token || reviewingId) return;
    const item = feedbacks.find(item => item.id === id);
    if (!item) return;
    const controller = new AbortController(); activeReview.current = controller;
    const epoch = requestEpoch.current;
    const current = () => epoch === requestEpoch.current && activeReview.current === controller
      && !controller.signal.aborted && savedAdminToken() === token;
    setReviewingId(id);
    try {
      const res = await fetch(`${API_BASE}/api/feedback/admin/${id}/${action}`, {
        method: 'POST',
        headers: { 'X-Admin-Token': token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ expectedRowVersion: item.rowVersion }), signal: controller.signal,
      });
      if (!current()) return;
      if (!res.ok) {
        setError(res.status === 409 ? '这条反馈已被其他审核更新，请刷新后重新核对'
          : res.status === 401 ? '管理口令已失效，请重新登录' : `${action === 'approve' ? '通过' : '拒绝'}失败（${res.status}）`);
        return;
      }
      const updated = decodeFeedbackReview(await res.json(), id, item.rowVersion, action === 'approve' ? 'approved' : 'rejected');
      if (!current()) return;
      setError('');
      setFeedbacks(previous => previous.map(row => row.id === id && row.rowVersion === item.rowVersion ? updated : row));
    } catch (error) {
      if (current()) setError(error instanceof FeedbackContractError ? error.message : '网络错误，操作失败');
    } finally {
      if (current()) setReviewingId(null);
    }
  }

  const visibleFeedbacks = useMemo(() => loadedToken === token ? feedbacks : [], [feedbacks, loadedToken, token]);
  const waiting = loading || (loadedToken !== token && !error);
  const titles = useMemo(
    () => Array.from(new Set(visibleFeedbacks.map((f) => f.soupTitle || f.soupId))),
    [visibleFeedbacks]
  );

  const shown = useMemo(() => {
    let list = visibleFeedbacks;
    if (soupFilter) {
      list = list.filter((f) => (f.soupTitle || f.soupId) === soupFilter);
    }
    if (statusFilter) {
      list = list.filter((f) => f.status === statusFilter);
    }
    return list;
  }, [visibleFeedbacks, soupFilter, statusFilter]);

  const pendingCount = useMemo(
    () => visibleFeedbacks.filter((f) => f.status === 'pending').length,
    [visibleFeedbacks]
  );

  function StatusBadge({ status, mergedAt }: { status: FeedbackStatus; mergedAt: string | null }) {
    if (status === 'approved') {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2.5 py-1 text-xs font-medium text-success">
          {mergedAt ? '✅ 已合并' : '已通过'}
        </span>
      );
    }
    if (status === 'rejected') {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 px-2.5 py-1 text-xs font-medium text-danger">
          已拒绝
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent-text">
        待审核
      </span>
    );
  }

  if (needToken) {
    return (
      <main className="mx-auto max-w-md px-4 py-16">
        <div className="card p-6">
          <h1 className="font-display text-xl font-bold">反馈管理后台</h1>
          <p className="muted mt-2 text-sm">请输入管理口令（与站点访问口令不同）才能查看玩家反馈。</p>
          <input
            className="input mt-4 w-full"
            type="password"
            placeholder="管理口令"
            value={inputToken}
            onChange={(e) => setInputToken(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submitToken()}
          />
          {error && <p className="mt-2 text-sm text-danger-strong">{error}</p>}
          <button className="btn btn-accent mt-4 w-full" onClick={submitToken}>
            进入
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full min-w-0 max-w-3xl px-4 py-6 sm:py-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="font-display text-xl font-bold">反馈管理后台</h1>
          <p className="muted mt-1 text-sm">这里主要用来核对玩家提交的回答问题。</p>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
          <select
            aria-label="按处理状态筛选"
            className="input w-full py-2 sm:w-auto sm:min-w-[8rem]"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as FeedbackStatus | '')}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            aria-label="按汤题筛选"
            className="input w-full py-2 sm:w-auto sm:min-w-[8rem]"
            value={soupFilter}
            onChange={(e) => setSoupFilter(e.target.value)}
          >
            <option value="">全部汤</option>
            {titles.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button className="btn btn-ghost w-full sm:w-auto" onClick={() => { setLoading(true); setError(''); void load(token); }} disabled={waiting || reviewingId !== null}>
            {waiting ? '刷新中…' : '刷新'}
          </button>
          <button
            className="btn btn-ghost w-full sm:w-auto"
            onClick={() => {
              localStorage.removeItem(ADMIN_TOKEN_KEY);
              window.dispatchEvent(new Event(ADMIN_TOKEN_EVENT));
            }}
          >
            退出
          </button>
        </div>
      </div>

      {error && <p className="mt-3 text-sm text-danger-strong">{error}</p>}

      <section className="card mt-5 p-4" aria-labelledby="feedback-list-heading">
        <div className="flex items-center justify-between gap-3">
          <h2 id="feedback-list-heading" className="font-display text-lg font-bold">待处理反馈</h2>
          <span className="rounded-full bg-accent/10 px-3 py-1 text-sm font-medium text-accent-text">{pendingCount} 条待处理</span>
        </div>
        <p className="muted mt-2 text-sm">依次核对“玩家问、主持人答、玩家认为应答”。确认有效只记录审核结果，不会直接修改线上回答规则。</p>
        <p className="muted mt-1 text-xs">最近7天共 {loadedToken === token ? total : 0} 条，当前已加载 {visibleFeedbacks.length} 条。</p>
      </section>

      <div className="mt-4 space-y-3">
        {shown.length === 0 && !waiting && (
          <div className="card p-6 text-center muted">
            {statusFilter || soupFilter ? '没有符合条件的反馈。' : '还没有玩家提交反馈。'}
          </div>
        )}
        {shown.map((f) => (
          <div key={f.id} className="card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="badge">{f.soupTitle || displayClaim(f.soupId)}</span>
                <StatusBadge status={f.status} mergedAt={f.mergedAt} />
                <span className="muted text-xs">审核版本：{f.rowVersion}</span>
              </div>
              <span className="muted text-xs">{fmtTime(f.ts)}</span>
            </div>

            <dl className="mt-3 space-y-2 text-sm">
              <div>
                <dt className="muted inline">玩家问：</dt>
                <dd className="inline">{displayClaim(f.question)}</dd>
              </div>
              <div>
                <dt className="muted inline">主持人答：</dt>
                <dd className="inline">{displayClaim(f.hostAnswer)}</dd>
              </div>
              <div>
                <dt className="text-accent inline">玩家认为应答：</dt>
                <dd className="inline">{displayClaim(f.expectedAnswer)}</dd>
              </div>
              {f.mergedAnswer && (
                <div>
                  <dt className="text-success inline">已标准化为：</dt>
                  <dd className="inline">{f.mergedAnswer}</dd>
                </div>
              )}
              {f.reason && (
                <div>
                  <dt className="muted inline">理由：</dt>
                  <dd className="inline">{f.reason}</dd>
                </div>
              )}
              {f.reviewedAt && (
                <div>
                  <dt className="muted inline">审批时间：</dt>
                  <dd className="inline">{fmtTime(f.reviewedAt)}</dd>
                </div>
              )}
              {f.mergedAt && (
                <div>
                  <dt className="muted inline">合并时间：</dt>
                  <dd className="inline">{fmtTime(f.mergedAt)}</dd>
                </div>
              )}
            </dl>

            {feedbackNeedsManualCorrection(f) && <p className="mt-3 text-sm text-danger-strong">
              必填内容仅空白：原历史记录已保留，可拒绝处理，不能通过或授权模型使用。
            </p>}

            {(f.status === 'pending' || (feedbackNeedsManualCorrection(f) && f.status !== 'rejected')) && (
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  className="btn btn-solid w-full bg-success text-white hover:bg-success/90 sm:w-auto"
                  onClick={() => review(f.id, 'approve')}
                  disabled={reviewingId !== null || feedbackNeedsManualCorrection(f)}
                >
                  确认反馈有效
                </button>
                <button
                  className="btn btn-ghost w-full border-danger/30 text-danger hover:bg-danger/10 sm:w-auto"
                  onClick={() => review(f.id, 'reject')}
                  disabled={reviewingId !== null}
                >
                  不采纳
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      {loadedToken === token && nextCursor && <button className="btn btn-ghost mt-4" disabled={waiting || reviewingId !== null}
        onClick={() => { setLoading(true); setError(''); void load(token, nextCursor); }}>加载更多</button>}

      <section className="card mt-6 p-4">
        <h2 className="font-display text-lg font-bold">高级功能</h2>
        <p className="muted mt-1 text-sm">平时审核反馈不需要使用。只有准备让 AI 分析并修改回答规则时才打开。</p>
        <button className="btn btn-ghost mt-3 w-full sm:w-auto" disabled={loadedToken !== token} aria-expanded={tasksOpen}
          onClick={() => setTasksOpen(previous => !previous)}>{tasksOpen ? '收起 AI 修正规则' : '高级：AI 修正规则'}</button>
      </section>
      {tasksOpen && loadedToken === token && <AgentReviewPanel token={token} feedbacks={visibleFeedbacks}
        onFeedbackChanged={updated => setFeedbacks(previous => previous.map(item => item.id === updated.id
          && item.rowVersion < updated.rowVersion ? updated : item))} />}

      <details className="card mt-4 overflow-hidden">
        <summary className="cursor-pointer list-none p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
          <span className="block font-semibold">高级：查看运行数据（平时不用）</span>
          <span className="muted mt-1 block text-sm">排查访问量或导出技术统计时再打开。</span>
        </summary>
        <div className="border-t border-border px-4 pb-4">
          <MetricsPanel adminToken={token} />
        </div>
      </details>
    </main>
  );
}
