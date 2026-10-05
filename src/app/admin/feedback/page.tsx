'use client';

import { useEffect, useMemo, useState } from 'react';

type FeedbackStatus = 'pending' | 'approved' | 'rejected';

type Feedback = {
  id: string;
  ts: string;
  soupId: string;
  soupTitle: string | null;
  question: string;
  hostAnswer: string;
  expectedAnswer: string;
  reason: string | null;
  status: FeedbackStatus;
  reviewedAt: string | null;
  mergedAt: string | null;
  mergedAnswer: string | null;
};

const ADMIN_TOKEN_KEY = 'turtle_admin_token';
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
  const [token, setToken] = useState('');
  const [inputToken, setInputToken] = useState('');
  const [needToken, setNeedToken] = useState(false);
  const [feedbacks, setFeedbacks] = useState<Feedback[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [soupFilter, setSoupFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<FeedbackStatus | ''>('');

  async function load(t: string) {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/feedback/admin`, {
        headers: { 'X-Admin-Token': t },
      });
      if (res.status === 401) {
        localStorage.removeItem(ADMIN_TOKEN_KEY);
        setToken('');
        setNeedToken(true);
        setError('管理口令错误，请重新输入');
        return;
      }
      if (!res.ok) {
        setError(`加载失败（${res.status}）`);
        return;
      }
      const data = (await res.json()) as { total: number; feedbacks: Feedback[] };
      setFeedbacks(data.feedbacks || []);
      setTotal(data.total || 0);
      setNeedToken(false);
    } catch {
      setError('网络错误，请确认后端已启动');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const saved = localStorage.getItem(ADMIN_TOKEN_KEY);
    if (saved) {
      setToken(saved);
      load(saved);
    } else {
      setNeedToken(true);
    }
  }, []);

  function submitToken() {
    const v = inputToken.trim();
    if (!v) return;
    localStorage.setItem(ADMIN_TOKEN_KEY, v);
    setToken(v);
    load(v);
  }

  async function review(id: string, action: 'approve' | 'reject') {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/api/feedback/admin/${id}/${action}`, {
        method: 'POST',
        headers: { 'X-Admin-Token': token },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || `${action === 'approve' ? '通过' : '拒绝'}失败`);
        return;
      }
      setError('');
      setFeedbacks((prev) =>
        prev.map((f) =>
          f.id === id
            ? {
                ...f,
                status: action === 'approve' ? 'approved' : 'rejected',
                reviewedAt: new Date().toISOString(),
              }
            : f
        )
      );
    } catch {
      setError('网络错误，操作失败');
    }
  }

  const titles = useMemo(
    () => Array.from(new Set(feedbacks.map((f) => f.soupTitle || f.soupId))),
    [feedbacks]
  );

  const shown = useMemo(() => {
    let list = feedbacks;
    if (soupFilter) {
      list = list.filter((f) => (f.soupTitle || f.soupId) === soupFilter);
    }
    if (statusFilter) {
      list = list.filter((f) => f.status === statusFilter);
    }
    return list;
  }, [feedbacks, soupFilter, statusFilter]);

  const pendingCount = useMemo(
    () => feedbacks.filter((f) => f.status === 'pending').length,
    [feedbacks]
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
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-bold">反馈管理后台</h1>
          <p className="muted text-sm">
            玩家提交的「主持人答错了」反馈 · 共 {total} 条
            {pendingCount > 0 && (
              <span className="ml-2 text-accent-text">（{pendingCount} 条待审核）</span>
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
          <button className="btn btn-ghost" onClick={() => load(token)} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              localStorage.removeItem(ADMIN_TOKEN_KEY);
              setToken('');
              setNeedToken(true);
            }}
          >
            退出
          </button>
        </div>
      </div>

      {error && <p className="mt-3 text-sm text-danger-strong">{error}</p>}

      <div className="mt-4 space-y-3">
        {shown.length === 0 && !loading && (
          <div className="card p-6 text-center muted">
            {statusFilter || soupFilter ? '没有符合条件的反馈。' : '还没有玩家提交反馈。'}
          </div>
        )}
        {shown.map((f) => (
          <div key={f.id} className="card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="badge">{f.soupTitle || f.soupId}</span>
                <StatusBadge status={f.status} mergedAt={f.mergedAt} />
              </div>
              <span className="muted text-xs">{fmtTime(f.ts)}</span>
            </div>

            <dl className="mt-3 space-y-2 text-sm">
              <div>
                <dt className="muted inline">玩家问：</dt>
                <dd className="inline">{f.question}</dd>
              </div>
              <div>
                <dt className="muted inline">主持人答：</dt>
                <dd className="inline">{f.hostAnswer}</dd>
              </div>
              <div>
                <dt className="text-accent inline">正确答案应为：</dt>
                <dd className="inline">{f.expectedAnswer}</dd>
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

            {f.status === 'pending' && (
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  className="btn btn-solid bg-success text-white hover:bg-success/90"
                  onClick={() => review(f.id, 'approve')}
                >
                  通过 ✅
                </button>
                <button
                  className="btn btn-ghost border-danger/30 text-danger hover:bg-danger/10"
                  onClick={() => review(f.id, 'reject')}
                >
                  拒绝 ❌
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
