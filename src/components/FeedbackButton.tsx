'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface SoupOption {
  id: string;
  title: string;
}

/**
 * 全局浮动「反馈」按钮：右下角常驻，点开弹窗收集
 * 「主持人回答与汤底出入」的 bug。表单顺序与用户定义一致：
 *   ① 选汤 → ② 你问的问题 → ③ 主持人回答 → ④ 你认为正确答案 → ⑤ 理由(选填)
 * 提交走 /api/feedback（apiFetch 自动带 X-Site-Token）。
 */
export default function FeedbackButton() {
  const pathname = usePathname();
  // 管理后台页面不需要这个按钮（避免管理员自己点自己审）。
  // 注意：这个判断不能在这里直接 return —— 它下面还有 12 个 useState/useEffect，
  // 在 /admin 下提前 return 会跳过这些 hooks，违反 React Hooks 规则（hooks 数量随路由变化）。
  // 因此这里只算一个布尔值，真正的 return 放到所有 hooks 之后。
  const hideOnAdmin = !!pathname && pathname.startsWith('/admin');

  const [open, setOpen] = useState(false);
  const [soups, setSoups] = useState<SoupOption[]>([]);
  const [soupId, setSoupId] = useState('');
  const [question, setQuestion] = useState('');
  const [hostAnswer, setHostAnswer] = useState('');
  const [expectedAnswer, setExpectedAnswer] = useState('');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  // 输入框聚焦时自动隐藏反馈按钮，避免遮挡输入内容；失焦后恢复
  const [inputFocused, setInputFocused] = useState(false);
  useEffect(() => {
    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')
      ) {
        setInputFocused(true);
      }
    };
    const onFocusOut = () => setInputFocused(false);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    return () => {
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('focusout', onFocusOut);
    };
  }, []);

  async function loadSoups() {
    try {
      const res = await apiFetch('/api/soups');
      const data = await res.json();
      setSoups(Array.isArray(data.soups) ? data.soups : []);
    } catch {
      setSoups([]);
    }
  }

  function openModal() {
    setError('');
    setDone(false);
    setOpen(true);
    loadSoups();
  }

  function close() {
    setOpen(false);
    setSoupId('');
    setQuestion('');
    setHostAnswer('');
    setExpectedAnswer('');
    setReason('');
  }

  const canSubmit =
    !!soupId && !!question.trim() && !!hostAnswer.trim() && !!expectedAnswer.trim() && !submitting;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await apiFetch('/api/feedback', {
        method: 'POST',
        body: JSON.stringify({
          soupId,
          question: question.trim(),
          hostAnswer: hostAnswer.trim(),
          expectedAnswer: expectedAnswer.trim(),
          reason: reason.trim() || undefined,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || '提交失败');
      }
      setDone(true);
      setSoupId('');
      setQuestion('');
      setHostAnswer('');
      setExpectedAnswer('');
      setReason('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  // 所有 hooks 已执行完毕，此处 return 不再破坏 hooks 顺序（管理后台隐藏按钮）
  if (hideOnAdmin) return null;

  return (
    <>
      {/* 左下角常驻浮动按钮：输入框聚焦时自动隐藏，避免遮挡输入内容 */}
      <button
        type="button"
        onClick={openModal}
        aria-label="主持人答错了？点此提交反馈"
        className={`fb-breathe fixed bottom-4 left-4 z-50 flex flex-col items-start gap-0.5 rounded-2xl bg-danger-strong px-3.5 py-2.5 font-bold text-white shadow-lg shadow-danger-strong/30 transition-all duration-200 hover:scale-105 active:scale-95 sm:px-5 sm:py-3 ${
          inputFocused ? 'pointer-events-none opacity-0' : 'opacity-100'
        }`}
      >
        <span className="text-xs leading-none sm:text-sm">主持人答错了？</span>
        <span className="text-[10px] font-medium leading-none text-white/85 sm:text-xs">点此提交反馈 →</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={close}
        >
          <div
            className="card max-h-[90vh] w-full max-w-lg animate-fade-up overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-display text-lg font-bold">提交主持人回答 Bug</h2>
              <button
                type="button"
                onClick={close}
                aria-label="关闭"
                className="btn btn-ghost h-8 w-8 p-0 text-fg-muted"
              >
                ×
              </button>
            </div>

            {done ? (
              <div className="space-y-4 py-6 text-center">
                <p className="text-success">✅ 提交成功，感谢反馈！</p>
                <button type="button" className="btn btn-solid" onClick={close}>
                  关闭
                </button>
              </div>
            ) : (
              <form onSubmit={submit} className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm text-fg-muted">① 哪个汤出了错？</label>
                  <select
                    value={soupId}
                    onChange={(e) => setSoupId(e.target.value)}
                    className="input"
                    required
                  >
                    <option value="">请选择汤…</option>
                    {soups.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-sm text-fg-muted">② 你问的问题是什么？</label>
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    className="input min-h-20"
                    placeholder="例如：故事中只有六个人吗？"
                    required
                  />
                </div>

                <div>
                  <label className="mb-1 block text-sm text-fg-muted">③ 主持人回答的是什么？</label>
                  <select
                    value={hostAnswer}
                    onChange={(e) => setHostAnswer(e.target.value)}
                    className="input"
                    required
                  >
                    <option value="">请选择主持人的回答…</option>
                    <option value="是">是</option>
                    <option value="不是">不是</option>
                    <option value="是也不是">是也不是</option>
                    <option value="算是">算是</option>
                    <option value="与此无关">与此无关</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-sm text-fg-muted">④ 你认为正确答案应该是什么？</label>
                  <select
                    value={expectedAnswer}
                    onChange={(e) => setExpectedAnswer(e.target.value)}
                    className="input"
                    required
                  >
                    <option value="">请选择标准答案…</option>
                    <option value="是">是</option>
                    <option value="不是">不是</option>
                    <option value="是也不是">是也不是</option>
                    <option value="算是">算是</option>
                    <option value="与此无关">与此无关</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-sm text-fg-muted">⑤ 理由（选填）</label>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    className="input min-h-16"
                    placeholder="可补充为什么你认为主持人答错了"
                  />
                </div>

                {error && <p className="text-xs text-danger">{error}</p>}

                <div className="flex justify-end gap-2 pt-1">
                  <button type="button" className="btn btn-ghost" onClick={close}>
                    取消
                  </button>
                  <button type="submit" className="btn btn-solid" disabled={!canSubmit}>
                    {submitting ? '提交中…' : '提交反馈'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}
