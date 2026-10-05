'use client';

import { useEffect, useState } from 'react';
import { apiFetch, getSiteToken, setSiteToken, clearSiteToken, API_BASE } from '@/lib/api';
import { LockIcon } from '@/components/icons';

/**
 * 站点访问口令闸门（客户端 UI 层）。
 * - 启动时询问后端 /api/config 是否开启口令；
 * - 若开启且本地无令牌 → 显示锁屏，输入口令后尝试带令牌拉取 /api/soups 验证；
 * - 验证通过则本地保存令牌，后续请求自动携带（真正的拦截在后端）。
 * 真正的防白嫖由后端 _require_token 兜底：没有正确令牌，/api/chat 直接 401。
 */
export default function SiteGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [locked, setLocked] = useState(false);
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch('/api/config');
        const data = await res.json();
        const siteLocked: boolean = !!data.siteLocked;
        if (siteLocked && !getSiteToken()) {
          setLocked(true);
        }
      } catch {
        // /api/config 不应被拦；若异常则默认不锁，避免把人挡在门外
      } finally {
        setReady(true);
      }
    })();
  }, []);

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setChecking(true);
    setError('');
    try {
      // 用输入的口令试拉一次列表，401 = 口令错误
      const res = await fetch(`${API_BASE}/api/soups`, {
        headers: { 'X-Site-Token': input.trim() },
      });
      if (res.status === 401) {
        setError('口令错误，请重试');
        clearSiteToken();
        return;
      }
      setSiteToken(input.trim());
      setLocked(false);
    } catch {
      setError('网络异常，请稍后重试');
    } finally {
      setChecking(false);
    }
  }

  // 后端还没探明状态前，先不渲染内容（避免闪烁）
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas text-fg-subtle">
        <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent-text" />
      </div>
    );
  }

  if (locked) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-canvas px-6 text-fg">
        <div className="card w-full max-w-sm animate-fade-up p-8 shadow-2xl shadow-black/40">
          <div className="mb-6 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-accent-text/20 bg-accent/10 text-accent-text">
              <LockIcon className="h-6 w-6" />
            </div>
            <h1 className="mt-3 font-display text-xl font-bold">许二木海龟汤自助</h1>
            <p className="mt-1 text-sm text-fg-subtle">请输入访问口令以进入</p>
          </div>
          <form onSubmit={unlock} className="space-y-3">
            <input
              type="password"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="访问口令"
              autoFocus
              aria-label="访问口令"
              className="input"
            />
            {error && <p className="text-xs text-danger">{error}</p>}
            <button
              type="submit"
              disabled={checking}
              className="btn btn-accent w-full"
            >
              {checking ? '验证中…' : '进入'}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
