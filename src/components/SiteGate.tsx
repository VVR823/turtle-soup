'use client';

import { useEffect, useRef, useState } from 'react';
import { apiJson, ApiAuthError, getSiteToken, setSiteToken } from '@/lib/api';
import { loadPublicCatalog } from '@/lib/catalog';
import { GameContractError } from '@/lib/game-contract';
import { LockIcon } from '@/components/icons';

/**
 * 站点访问口令闸门（客户端 UI 层）。
 * - 启动时询问后端 /api/config 是否开启口令；
 * - 若开启且本地无令牌 → 显示锁屏，输入口令后尝试带令牌拉取 /api/soups 验证；
 * - 验证通过则本地保存令牌，后续请求自动携带（真正的拦截在后端）。
 * 真正的防白嫖由后端 _require_token 兜底：没有正确令牌，/api/chat 直接 401。
 */
export default function SiteGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<'checking' | 'locked' | 'verified' | 'unavailable'>('checking');
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const active = useRef<AbortController | null>(null);
  const submitting = useRef(false);

  useEffect(() => {
    const controller = new AbortController(); active.current = controller;
    const current = () => active.current === controller && !controller.signal.aborted;
    (async () => {
      try {
        const data = await apiJson('/api/config', { signal: controller.signal });
        if (!current()) return;
        if (!data || typeof data !== 'object' || Array.isArray(data) || typeof (data as { siteLocked?: unknown }).siteLocked !== 'boolean') throw new GameContractError();
        if (!(data as { siteLocked: boolean }).siteLocked) { setStatus('verified'); return; }
        const token = getSiteToken();
        if (!token) { setStatus('locked'); return; }
        await loadPublicCatalog({ token, signal: controller.signal });
        if (!current()) return;
        if (getSiteToken() !== token) throw new GameContractError('口令状态已变化，请重新检查站点');
        setStatus('verified');
      } catch (error) {
        if (!current()) return;
        setError(error instanceof ApiAuthError ? '口令错误，请重试' : '站点服务暂时不可用，请重新检查');
        setStatus(error instanceof ApiAuthError ? 'locked' : 'unavailable');
      }
    })();
    return () => { controller.abort(); if (active.current === controller) active.current = null; };
  }, [attempt]);

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || submitting.current || status !== 'locked') return;
    const controller = active.current;
    if (!controller || controller.signal.aborted) return;
    const token = input.trim();
    const current = () => active.current === controller && !controller.signal.aborted;
    submitting.current = true;
    setChecking(true);
    setError('');
    try {
      const previousToken = getSiteToken();
      await loadPublicCatalog({ token, signal: controller.signal });
      if (!current()) return;
      if (getSiteToken() !== previousToken) throw new GameContractError('口令状态已变化，请重新验证');
      setSiteToken(token);
      setStatus('verified');
    } catch (error) {
      if (current()) setError(error instanceof ApiAuthError ? '口令错误，请重试' : '验证未完成，请稍后重试');
    } finally {
      submitting.current = false;
      if (current()) setChecking(false);
    }
  }

  // 后端还没探明状态前，先不渲染内容（避免闪烁）
  if (status === 'unavailable') {
    return <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-canvas text-fg">
      <p role="alert">{error}</p>
      <button className="btn btn-accent" onClick={() => { setStatus('checking'); setError(''); setAttempt(value => value + 1); }}>重新检查站点</button>
    </div>;
  }
  if (status === 'checking') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas text-fg-subtle">
        <span role="status" aria-label="正在检查站点" className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent-text" />
      </div>
    );
  }

  if (status === 'locked') {
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
            {error && <p role="alert" className="text-xs text-danger">{error}</p>}
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
