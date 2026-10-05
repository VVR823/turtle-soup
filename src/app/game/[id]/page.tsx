'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, useParams, useSearchParams } from 'next/navigation';
import { Message } from '@/types';
import { apiFetch, clearSiteToken, ApiAuthError, addUnlockedSoup, saveLastSession, getLastSession, addPlayedSoup } from '@/lib/api';
import {
  TurtleIcon, ArrowLeftIcon, MaskIcon, GiftIcon, ScrollIcon, ClipboardIcon,
  TargetIcon, TrophyIcon, RefreshIcon, FlagIcon, CloseIcon, CheckIcon, AlertIcon,
  SparkleIcon, CoffeeIcon, SearchIcon,
} from '@/components/icons';

/** 海龟汤聊天界面 - 左右分栏布局 */
export default function GamePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const soupId = params.id || '';
  const level = searchParams.get('level') || '';

  const [sessionId, setSessionId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [soupTitle, setSoupTitle] = useState('');
  const [gameOver, setGameOver] = useState(false);
  const [won, setWon] = useState(false); // 隐藏彩蛋汤通关
  const [questionLimit, setQuestionLimit] = useState<number | null>(null); // null=不限
  const [remaining, setRemaining] = useState<number | null>(null);
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [unlocks, setUnlocks] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<{
    completion: number;
    evaluation: string;
    keyPointsCovered: string[];
    keyPointsMissing: string[];
    bottom: string;
    unlockSoupId?: string | null;
  } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reviewCloseRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!soupId) { alert('请先选择一道汤！'); router.push('/'); return; }
    // 刷新/重开页面后尝试恢复上一局（同汤同难度才恢复）；恢复失败或没有则开新局
    const saved = getLastSession();
    if (saved && saved.soupId === soupId && saved.level === level) {
      restoreSession(saved.sessionId).then(ok => {
        if (!ok) startNewGame();
      });
    } else {
      startNewGame();
    }
    // 依赖必须含 level：从难度选择页切换难度时路由不变（同为 /game/[id]，只有 query 变化），
    // 组件不会重新挂载；若只依赖 soupId，切换难度后会继续停留在上一局，看起来像"没反应"。
    // startNewGame 是组件内函数声明，每次渲染引用都会变，放进依赖会导致 effect 反复触发；
    // 它实际只依赖 soupId/level，这两个值已显式列入，故有意不列函数本身。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soupId, level, router]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (!loading) inputRef.current?.focus();
  }, [loading]);

  // 复盘模态：Esc 关闭 + 打开聚焦关闭按钮
  useEffect(() => {
    if (!showReviewModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowReviewModal(false);
    };
    window.addEventListener('keydown', onKey);
    reviewCloseRef.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [showReviewModal]);

  /** 恢复上次未结束的会话：拉回汤面、剩余次数与完整问答历史。 */
  async function restoreSession(sid: string): Promise<boolean> {
    try {
      const res = await apiFetch(`/api/session/${sid}`);
      if (!res.ok) return false;
      const data = await res.json();
      setSessionId(data.sessionId);
      setSoupTitle(data.soupTitle);
      setQuestionLimit(data.questionLimit ?? null);
      setRemaining(data.remaining ?? null);
      setUnlocks(data.unlocks ?? null);
      const history = (data.messages || []).map((m: { role: string; content: string; timestamp: number }) => ({
        role: m.role as 'user' | 'host',
        content: m.content,
        timestamp: m.timestamp,
      }));
      setMessages([
        { role: 'host', content: data.soupSurface, timestamp: Date.now() },
        ...history,
      ]);
      setGameOver(false);
      setEvaluation(null);
      setWon(false);
      return true;
    } catch {
      return false;
    }
  }

  async function startNewGame() {
    try {
      const res = await apiFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ soupId, level }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `请求失败（${res.status}）`);
      if (data.error) throw new Error(data.error);
      setSessionId(data.sessionId);
      setSoupTitle(data.soupTitle);
      setQuestionLimit(data.questionLimit ?? null);
      setRemaining(data.questionLimit ?? null);
      setUnlocks(data.unlocks ?? null);
      setMessages([{ role: 'host', content: data.soupSurface, timestamp: Date.now() }]);
      setGameOver(false);
      setEvaluation(null);
      setEvaluating(false);
      setWon(false);
      // 记录上一局，刷新/重开页面后可恢复
      saveLastSession({ sessionId: data.sessionId, soupId, level });
    } catch (err) {
      if (err instanceof ApiAuthError) {
        clearSiteToken();
        window.location.reload();
        return;
      }
      alert('游戏创建失败，请重试');
    }
  }

  async function sendMessage(msg: string) {
    if (!msg.trim() || loading || evaluating) return;
    setLoading(true);
    try {
      setMessages(prev => [...prev, { role: 'user', content: msg, timestamp: Date.now() }]);
      const res = await apiFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ question: msg, sessionId, soupId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `请求失败（${res.status}）`);
      setMessages(prev => [...prev, { role: 'host', content: data.reply, timestamp: Date.now() }]);
      if (data.remaining != null) setRemaining(data.remaining);
      if (data.limitReached) {
        setRemaining(0);
        await evaluateAndReveal();
      }
      if (data.isReveal) setGameOver(true);
      if (data.isWin) {
        setWon(true);
        await evaluateAndReveal(); // 命中通关条件：展示 100% 结局面板
      }
    } catch (err) {
      if (err instanceof ApiAuthError) {
        clearSiteToken();
        window.location.reload();
        return;
      }
      // 网络/后端异常（如每晚 0 点更新窗口）：聊天区显示友好错误气泡，而不是静默空白。
      // 这类失败请求没有扣次数，提示玩家直接重发。
      const hint = err instanceof Error && err.message ? err.message : '网络开小差了';
      setMessages(prev => [...prev, { role: 'host', content: `⚠️ ${hint}，请重新发送你的问题（不会扣次数）`, timestamp: Date.now() }]);
    } finally {
      setLoading(false);
      if (inputRef.current && !gameOver && !evaluating && !(remaining != null && remaining <= 0)) inputRef.current.focus();
    }
  }

  async function evaluateAndReveal() {
    if (!sessionId || evaluating || evaluation) return;
    setEvaluating(true);
    try {
      const res = await apiFetch('/api/evaluate', {
        method: 'POST',
        body: JSON.stringify({ sessionId }),
      });
      const data = await res.json();
      if (!res.ok || data.error || data.detail) {
        throw new Error(data.error || data.detail || `揭晓答案失败 (${res.status})`);
      }
      setEvaluation(data);
      setGameOver(true);
      // 看过答案/汤底 → 按用户口径标记"玩过"；本局结束，清除待恢复会话（下次进来开新局）
      addPlayedSoup(soupId);
      saveLastSession(null);
      // 如果复盘解锁了隐藏彩蛋，记录到本地
      if (data.unlockSoupId) {
        addUnlockedSoup(data.unlockSoupId);
      }
    } catch (err) {
      if (err instanceof ApiAuthError) {
        clearSiteToken();
        window.location.reload();
        return;
      }
      console.error(err);
      alert('揭晓答案失败，请重试');
    } finally {
      setEvaluating(false);
    }
  }

  function handleSubmit(e: React.FormEvent) { e.preventDefault(); sendMessage(question); setQuestion(''); }

  const surface = messages[0]?.content || '';
  const chatMessages = messages.slice(1);

  return (
    <div className="flex h-screen flex-col bg-canvas text-fg font-sans">
      {/* ====== 顶部导航栏 ====== */}
      <header className="flex shrink-0 items-center gap-3 border-b border-border/70 bg-surface/60 px-5 py-3 backdrop-blur-sm">
        <button
          onClick={() => { saveLastSession(null); router.push('/'); }}
          className="btn btn-ghost shrink-0 px-2 py-2"
          aria-label="返回大厅"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          返回大厅
        </button>
        <button
          onClick={() => router.push(`/difficulty/${soupId}`)}
          className="btn btn-ghost shrink-0 px-2 py-2"
          aria-label="选择难度"
          title="返回难度选择页"
        >
          <MaskIcon className="h-4 w-4" />
          选难度
        </button>
        <h2 className="flex-1 truncate px-2 text-center font-display text-base font-bold text-accent-text">
          <TurtleIcon className="mr-1 inline-block h-4 w-4 align-[-2px]" />
          {soupTitle || '加载中…'}
        </h2>
        <div className="flex w-16 shrink-0 justify-end">
          {questionLimit != null ? (
            <span
              className={`rounded-full border px-3 py-1 text-xs font-medium ${
                (remaining != null && remaining <= 5)
                  ? 'border-danger/30 bg-danger/10 text-danger'
                  : 'border-accent/30 bg-accent/5 text-accent-text/90'
              }`}
              aria-live="polite"
            >
              {remaining}/{questionLimit}
            </span>
          ) : (
            <span className="rounded-full border border-success/30 bg-success/5 px-3 py-1 text-xs font-medium text-success/90">
              不限次
            </span>
          )}
        </div>
      </header>

      {/* ====== 主体：手机上下堆叠 / 电脑左右分栏 ====== */}
      <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
        {/* ---- 左栏：汤面 ---- */}
        {/* 手机端固定 35vh，内部滚动；电脑端恢复左侧固定宽度面板 */}
        <aside className="h-[35vh] shrink-0 overflow-y-auto border-b border-border/70 bg-surface/30 lg:h-auto lg:max-h-none lg:w-[38%] lg:min-w-[300px] lg:max-w-[480px] lg:shrink-0 lg:border-b-0 lg:border-r">
          <div className="space-y-4 p-5">
            {/* 汤面卡片 */}
            <div className="panel relative overflow-hidden p-5">
              <div className="absolute left-8 right-8 top-0 h-px bg-gradient-to-r from-transparent via-accent-text/25 to-transparent" />
              <div className="mb-3 mt-1 flex items-center gap-2">
                <ScrollIcon className="h-4 w-4 text-accent-text/80" />
                <span className="text-xs font-bold uppercase tracking-widest text-accent-text/80">汤面</span>
                <div className="h-px flex-1 bg-gradient-to-r from-accent-text/10 to-transparent" />
              </div>
              <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-fg-muted">
                {surface}
              </p>
            </div>

            {/* 隐藏彩蛋解锁提示 */}
            {unlocks && questionLimit != null && (
              <div className="panel relative overflow-hidden border-accent-text/25 bg-gradient-to-br from-accent/10 to-accent/5 p-4 shadow-sm shadow-accent/10">
                <div className="absolute left-0 top-0 h-0.5 w-full bg-gradient-to-r from-transparent via-accent-text/50 to-transparent" />
                <div className="flex items-start gap-3">
                  <GiftIcon className="h-5 w-5 shrink-0 text-accent-text" />
                  <div>
                    <div className="mb-1 text-sm font-bold text-accent-text">隐藏彩蛋等你解锁</div>
                    <p className="text-xs leading-relaxed text-accent-text/85">
                      通关本汤并达到解锁门槛，即可解锁一道隐藏海龟汤。
                      <span className="font-medium text-accent-text">彩蛋汤不限制提问次数，直到你们认输为止。</span>
                      尽可能还原当前真相吧！
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* 提示区 */}
            <div className="panel border-border/50 p-4">
              <p className="text-xs leading-relaxed text-fg-subtle">
                {questionLimit == null ? (
                  <>
                    <GiftIcon className="mr-1 inline-block h-3.5 w-3.5 align-[-2px] text-accent-text/80" />
                    这是一道<span className="mx-1 text-accent-text/80">隐藏彩蛋汤</span>。
                    主持人会回答你所有「是/不是」类问题，<span className="mx-1 text-success/80">不限次数</span>，直到你认输揭晓汤底。
                  </>
                ) : (
                  <>
                    <SparkleIcon className="mr-1 inline-block h-3.5 w-3.5 align-[-2px] text-accent-text/80" />
                    通过提问来推理真相。主持人只会回答：
                    <span className="mx-1 text-accent-text/80">是、不是、是也不是（有对有错）、算是（大致对）、与此无关</span>
                    ，也可以给出提示。
                  </>
                )}
              </p>
              <button
                onClick={() => setShowReviewModal(true)}
                className="btn btn-ghost mt-3 w-full"
              >
                <ClipboardIcon className="h-4 w-4" />
                复个小盘（查看问答记录）
              </button>
              <div className="mt-3 border-t border-border/40 pt-3">
                <button
                  onClick={() => evaluateAndReveal()}
                  disabled={gameOver || evaluating}
                  className="btn btn-accent w-full"
                >
                  {evaluating ? (
                    <>
                      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent-text/40 border-t-accent-text" />
                      正在复盘…
                    </>
                  ) : questionLimit == null ? (
                    <>
                      <FlagIcon className="h-4 w-4" />
                      我认输 / 揭晓汤底
                    </>
                  ) : (
                    <>
                      <FlagIcon className="h-4 w-4" />
                      揭晓答案
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </aside>

        {/* ---- 右栏：聊天区域 ---- */}
        <main className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          {/* 聊天消息列表 */}
          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
            {chatMessages.length === 0 && !loading && (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-fg-subtle">
                <SearchIcon className="h-10 w-10 opacity-20" />
                <p className="text-sm">向主持人提问，开始你的推理</p>
                <p className="text-xs text-fg-subtle/70">左侧是汤面，随时可以回顾</p>
              </div>
            )}

            {chatMessages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-message-in`}>
                {msg.role === 'host' ? (
                  <div className="flex max-w-[85%] items-start gap-2.5">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-accent-text/20 bg-accent/10 text-accent-text">
                      <MaskIcon className="h-4 w-4" />
                    </div>
                    <div className="rounded-2xl rounded-tl-sm border border-accent-text/10 bg-surface px-4 py-2.5 text-sm leading-relaxed text-fg shadow-sm">
                      {msg.content}
                    </div>
                  </div>
                ) : (
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm border border-accent-text/15 bg-accent/10 px-4 py-2.5 text-sm leading-relaxed text-fg shadow-sm">
                    {msg.content}
                  </div>
                )}
              </div>
            ))}

            {/* 加载中动画 */}
            {loading && (
              <div className="flex items-start gap-2.5">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-accent-text/20 bg-accent/10 text-accent-text">
                  <MaskIcon className="h-4 w-4" />
                </div>
                <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-accent-text/10 bg-surface px-4 py-3">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent-text/60" style={{ animationDelay: '0ms' }} />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent-text/60" style={{ animationDelay: '150ms' }} />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent-text/60" style={{ animationDelay: '300ms' }} />
                  <span className="ml-1 text-xs text-fg-muted">主持人思考中…</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* 游戏结束覆盖层：完成度评价 + 完整汤底 */}
          {evaluation && (
            <div className="absolute inset-0 z-20 space-y-4 overflow-y-auto bg-canvas px-6 py-5">
              <div className="flex items-center gap-3">
                {won ? <TrophyIcon className="h-6 w-6 text-accent-text" /> : <TargetIcon className="h-6 w-6 text-accent-text" />}
                <div>
                  <div className="text-base font-bold text-accent-text">{won ? '通关！' : '真相揭晓'}</div>
                  <div className="text-xs text-fg-subtle">{won ? '你已看穿隐藏彩蛋的终极真相' : 'AI 根据本局问答自动评估的还原完成度'}</div>
                </div>
                <div className="ml-auto text-right">
                  <div className="text-xl font-bold text-accent-text">{evaluation.completion}%</div>
                  <div className="text-[10px] text-fg-subtle">完成度</div>
                </div>
              </div>

              <div className="h-2 w-full rounded-full bg-border">
                <div
                  className="h-2 rounded-full bg-gradient-to-r from-accent to-accent-text transition-all"
                  style={{ width: `${evaluation.completion}%` }}
                />
              </div>

              <p className="text-sm leading-relaxed text-fg-muted">{evaluation.evaluation}</p>

              {evaluation.keyPointsCovered && evaluation.keyPointsCovered.length > 0 && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-success">
                    <CheckIcon className="h-3.5 w-3.5" /> 已触及的关键点
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {evaluation.keyPointsCovered.map((p, i) => (
                      <span key={i} className="flex items-center gap-1 rounded-full border border-success/20 bg-success/10 px-2 py-0.5 text-[11px] text-success/90">
                        <CheckIcon className="h-3 w-3" />
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {evaluation.keyPointsMissing && evaluation.keyPointsMissing.length > 0 && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-danger">
                    <CloseIcon className="h-3.5 w-3.5" /> 尚未触及的关键点
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {evaluation.keyPointsMissing.map((p, i) => (
                      <span key={i} className="flex items-center gap-1 rounded-full border border-danger/20 bg-danger/10 px-2 py-0.5 text-[11px] text-danger/90">
                        <CloseIcon className="h-3 w-3" />
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="panel border-border/60 p-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-accent-text/80">
                  <ScrollIcon className="h-3.5 w-3.5" /> 完整汤底
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg-muted">{evaluation.bottom}</p>
              </div>

              {evaluation.unlockSoupId && (
                <div className="panel border-accent-text/20 bg-accent/10 p-3 text-center">
                  <div className="flex items-center justify-center gap-1.5 text-sm font-bold text-accent-text">
                    <GiftIcon className="h-4 w-4" /> 隐藏彩蛋已解锁！
                  </div>
                  <p className="mt-1 text-xs text-accent-text/70">
                    返回大厅即可看到新的海龟汤。
                  </p>
                </div>
              )}

              <div className="flex justify-center gap-3 pt-1">
                <button
                  onClick={() => { setMessages([]); setEvaluation(null); setGameOver(false); startNewGame(); }}
                  className="btn btn-accent"
                >
                  <RefreshIcon className="h-4 w-4" />
                  再来一局
                </button>
                <button
                  onClick={() => { saveLastSession(null); router.push('/'); }}
                  className="btn btn-ghost"
                >
                  <ArrowLeftIcon className="h-4 w-4" />
                  返回大厅
                </button>
              </div>

              <p className="center pt-1 text-center text-xs text-fg-subtle">
                觉得好玩？欢迎到首页 <CoffeeIcon className="inline-block h-3.5 w-3.5 align-[-2px]" /> 请作者喝杯奶茶~
              </p>
            </div>
          )}

          {/* ---- 底部输入框（通栏） ---- */}
          {!gameOver && !evaluating && (
            <div className="shrink-0 border-t border-border/70 bg-surface/60 px-4 py-3 pb-5 backdrop-blur-sm sm:pb-3">
              {questionLimit != null && remaining != null && remaining <= 0 ? (
                <div className="flex items-center justify-center gap-2 py-1 text-sm text-danger/90">
                  <AlertIcon className="h-4 w-4" />
                  本局提问次数已用完，正在揭晓真相…
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="flex items-center gap-2.5">
                  <input
                    ref={inputRef}
                    type="text"
                    value={question}
                    onChange={e => setQuestion(e.target.value)}
                    placeholder="输入你的问题（例如：主角是盲人吗？）"
                    aria-label="向主持人提问"
                    disabled={loading || evaluating}
                    className="input flex-1 text-base"
                  />
                  <button
                    type="submit"
                    disabled={loading || evaluating || !question.trim()}
                    className="btn btn-solid shrink-0"
                  >
                    发送
                  </button>
                </form>
              )}
            </div>
          )}
        </main>
      </div>

      {/* ====== 复个小盘模态框 ====== */}
      {showReviewModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-6 backdrop-blur-sm"
          onClick={() => setShowReviewModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="review-title"
        >
          <div
            className="card flex max-h-[85vh] w-[560px] max-w-[92vw] flex-col overflow-hidden shadow-2xl shadow-black/50"
            onClick={e => e.stopPropagation()}
          >
            {/* 标题栏 */}
            <div className="flex shrink-0 items-center justify-between border-b border-border/70 px-6 py-4">
              <div className="flex items-center gap-3">
                <ClipboardIcon className="h-5 w-5 text-accent-text" />
                <div>
                  <h3 id="review-title" className="text-base font-bold text-accent-text">复个小盘</h3>
                  <p className="mt-0.5 text-xs text-fg-subtle">已进行 {chatMessages.filter(m => m.role === 'user').length} 轮提问</p>
                </div>
              </div>
              <button
                ref={reviewCloseRef}
                onClick={() => setShowReviewModal(false)}
                className="btn btn-ghost -mr-2 px-2 py-2"
                aria-label="关闭复盘"
              >
                <CloseIcon className="h-5 w-5" />
              </button>
            </div>

            {/* 问答列表 */}
            <div className="flex-1 space-y-3 overflow-y-auto px-6 py-4">
              {chatMessages.length === 0 && (
                <p className="py-8 text-center text-sm text-fg-subtle">还没有任何提问，先去问问主持人吧~</p>
              )}
              {chatMessages.map((msg, i) => {
                if (msg.role !== 'user') return null;
                const hostReply = chatMessages[i + 1]?.role === 'host' ? chatMessages[i + 1].content : '';
                const isFree = hostReply.startsWith('🤔') || hostReply.startsWith('🎯') || hostReply.startsWith('⚠️') || hostReply.startsWith('🤖');
                return (
                  <div key={i} className="panel border-border/60 p-3.5">
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-accent-text/20 bg-accent/10 text-[10px] font-medium text-accent-text/80">Q</span>
                      <p className="flex-1 text-sm leading-relaxed text-fg">{msg.content}</p>
                    </div>
                    <div className="mt-2.5 flex items-start gap-2 pl-7">
                      <span className="mt-0.5 text-[11px] font-medium text-accent-text/60">A</span>
                      <p className={`flex-1 text-sm leading-relaxed ${isFree ? 'italic text-fg-subtle' : 'text-fg-muted'}`}>
                        {hostReply || '（等待主持人回复…）'}
                      </p>
                      {isFree && (
                        <span className="shrink-0 whitespace-nowrap rounded border border-border px-1.5 py-0.5 text-[10px] text-fg-subtle">
                          未计入次数
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* 底部按钮 */}
            <div className="shrink-0 border-t border-border/70 bg-surface/50 px-6 py-4">
              <button
                onClick={() => setShowReviewModal(false)}
                className="btn btn-accent w-full"
              >
                继续推理
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
