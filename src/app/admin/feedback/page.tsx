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
    <main className="mx-auto w-full min-w-0 max-w-3xl px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-bold">反馈管理后台</h1>
          <p className="muted text-sm">
            最近7天反馈 · 范围内 {loadedToken === token ? total : 0} 条 · 已加载 {visibleFeedbacks.length} 条
            {pendingCount > 0 && (
              <span className="ml-2 text-accent-text">（已加载中 {pendingCount} 条待审核）</span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="input w-auto min-w-[8rem] py-2"
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
            className="input w-auto min-w-[8rem] py-2"
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
          <button className="btn btn-ghost" onClick={() => { setLoading(true); setError(''); void load(token); }} disabled={waiting || reviewingId !== null}>
            {waiting ? '刷新中…' : '刷新'}
          </button>
          <button
            className="btn btn-ghost"
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

      <MetricsPanel adminToken={token} />

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
                  className="btn btn-solid bg-success text-white hover:bg-success/90"
                  onClick={() => review(f.id, 'approve')}
                  disabled={reviewingId !== null || feedbackNeedsManualCorrection(f)}
                >
                  通过 ✅
                </button>
                <button
                  className="btn btn-ghost border-danger/30 text-danger hover:bg-danger/10"
                  onClick={() => review(f.id, 'reject')}
                  disabled={reviewingId !== null}
                >
                  拒绝 ❌
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      {loadedToken === token && nextCursor && <button className="btn btn-ghost mt-4" disabled={waiting || reviewingId !== null}
        onClick={() => { setLoading(true); setError(''); void load(token, nextCursor); }}>加载更多</button>}
      <button className="btn btn-ghost mt-4" disabled={loadedToken !== token} aria-expanded={tasksOpen}
        onClick={() => setTasksOpen(previous => !previous)}>{tasksOpen ? '关闭任务管理' : '打开任务管理'}</button>
      {tasksOpen && loadedToken === token && <AgentReviewPanel token={token} feedbacks={visibleFeedbacks}
        onFeedbackChanged={updated => setFeedbacks(previous => previous.map(item => item.id === updated.id
          && item.rowVersion < updated.rowVersion ? updated : item))} />}
    </main>
  );
}
