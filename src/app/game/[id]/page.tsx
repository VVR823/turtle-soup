'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, useParams, useSearchParams } from 'next/navigation';
import { normalizeEvaluationDisplay } from '@/lib/evaluation';
import { useGameController } from '@/lib/use-game-controller';
import type { GameTarget } from '@/lib/game-journal';
import { feedbackTurn } from '@/lib/feedback-turn';
import FeedbackButton from '@/components/FeedbackButton';
import {
  TurtleIcon, ArrowLeftIcon, MaskIcon, GiftIcon, ScrollIcon, ClipboardIcon,
  TargetIcon, TrophyIcon, RefreshIcon, FlagIcon, CloseIcon, CheckIcon, AlertIcon,
  SparkleIcon, CoffeeIcon, SearchIcon,
} from '@/components/icons';

/** 海龟汤聊天界面 - 左右分栏布局 */
export default function GamePage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const soupId = params.id || '';
  const level = searchParams.get('level') || '';
  return <GameView key={JSON.stringify([soupId, level])} target={{ soupId, level }} />;
}

function GameView({ target }: { target: GameTarget }) {
  const router = useRouter();
  const { soupId } = target;
  const { state, controller } = useGameController(target);
  const session = state.session;
  const [question, setQuestion] = useState('');
  const [showReviewModal, setShowReviewModal] = useState(false);
  const loading = state.phase === 'asking';
  const evaluating = state.phase === 'revealing';
  const busy = ['initializing', 'asking', 'revealing'].includes(state.phase);
  const canAsk = state.phase === 'playing' && !!session && session.status === 'playing' && !session.ruleSuspended && !state.pending;
  const gameOver = !!session && session.status !== 'playing';
  const won = session?.status === 'solved';
  const soupTitle = session?.soupTitle || '';
  const questionLimit = session?.questionLimit ?? null;
  const remaining = session?.remaining ?? null;
  const unlocks = session?.unlocks;
  const evaluation = session?.evaluation || null;
  const chatMessages = session?.messages || [];
  const surface = session?.soupSurface || '';
  const evaluationDisplay = evaluation ? normalizeEvaluationDisplay(evaluation) : null;
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reviewCloseRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [session?.messages, loading]);

  useEffect(() => {
    if (canAsk) inputRef.current?.focus();
  }, [canAsk]);

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

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canAsk || !question.trim()) return;
    void controller.ask(question); setQuestion('');
  }
  function restart() {
    if (state.pending && !window.confirm('这次请求可能已提交，另开会放弃它的恢复入口，但不会删除服务端历史。确定另开吗？')) return;
    void controller.restart(!!state.pending);
  }

  return (
    <div className="flex h-screen flex-col bg-canvas text-fg font-sans">
      {/* ====== 顶部导航栏 ====== */}
      <header className="flex shrink-0 items-center gap-3 border-b border-border/70 bg-surface/60 px-5 py-3 backdrop-blur-sm">
        <button
          onClick={() => router.push('/')}
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
          {!session ? <span role="status" className="text-xs text-fg-muted">同步中</span> : questionLimit != null ? (
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

      {session?.ruleSuspended && <section className="shrink-0 border-b border-border px-5 py-3 text-sm" aria-live="polite">
        <p>此版本规则已暂停，新提问和揭晓暂不可用；原对局与历史已保留，已结束的评估仍可查看。</p>
        <button className="btn btn-ghost mt-2" disabled={busy} onClick={() => void controller.synchronize()}>检查暂停是否解除</button>
      </section>}
      {(state.error || state.phase === 'initializing' || state.phase === 'syncing') && (
        <section className="shrink-0 border-b border-border px-5 py-3 text-sm" aria-live="polite">
          <p role={state.error ? 'alert' : 'status'}>{state.error?.message || '正在同步原对局…'}</p>
          {state.pending && <p className="mt-1 text-xs text-fg-muted">提交结果尚未确定，保留原请求同步，不要重复新提问。</p>}
          {state.error?.retryAfterSeconds != null && <p>请等待 {state.error.retryAfterSeconds} 秒后再同步。</p>}
          {!busy && (state.error || state.phase === 'syncing') && (
            <div className="mt-2 flex flex-wrap gap-2">
              <button className="btn btn-ghost" onClick={() => void controller.synchronize()}>同步原对局</button>
              {state.error?.category === 'auth' && <button className="btn btn-ghost" onClick={() => window.location.reload()}>重新验证口令</button>}
              <button className="btn btn-ghost" onClick={restart}>{state.pending ? '放弃待同步请求并另开' : '另开一局'}</button>
            </div>
          )}
        </section>
      )}

      {/* ====== 主体：手机上下堆叠 / 电脑左右分栏 ====== */}
      <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
        {/* ---- 左栏：汤面 ---- */}
        {/* 手机端固定 35vh，内部滚动；电脑端恢复左侧固定宽度面板 */}
        <aside className="h-[35vh] shrink-0 overflow-y-auto border-b border-border/70 bg-surface/30 lg:mb-20 lg:h-auto lg:max-h-none lg:w-[38%] lg:min-w-[300px] lg:max-w-[480px] lg:shrink-0 lg:border-b-0 lg:border-r">
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
                {session && questionLimit == null ? (
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
                  onClick={() => void controller.reveal()}
                  disabled={!canAsk || gameOver || busy}
                  className="btn btn-accent w-full"
                >
                  {evaluating ? (
                    <>
                      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent-text/40 border-t-accent-text" />
                      正在复盘…
                    </>
                  ) : session && questionLimit == null ? (
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

            {chatMessages.map((msg, i) => {
              const feedbackSource = session ? feedbackTurn(session, i) : null;
              return (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-message-in`}>
                {msg.role === 'host' ? (
                  <div className="flex max-w-[85%] items-start gap-2.5">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-accent-text/20 bg-accent/10 text-accent-text">
                      <MaskIcon className="h-4 w-4" />
                    </div>
                    <div className="rounded-2xl rounded-tl-sm border border-accent-text/10 bg-surface px-4 py-2.5 text-sm leading-relaxed text-fg shadow-sm">
                      <p>{msg.content}</p>
                      {feedbackSource && <FeedbackButton key={feedbackSource.turnId} source={feedbackSource} />}
                    </div>
                  </div>
                ) : (
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm border border-accent-text/15 bg-accent/10 px-4 py-2.5 text-sm leading-relaxed text-fg shadow-sm">
                    {msg.content}
                  </div>
                )}
              </div>
              );
            })}

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
          {evaluation && evaluationDisplay && (
            <div className="absolute inset-0 z-20 space-y-4 overflow-y-auto bg-canvas px-6 py-5">
              <div className="flex items-center gap-3">
                {won ? <TrophyIcon className="h-6 w-6 text-accent-text" /> : <TargetIcon className="h-6 w-6 text-accent-text" />}
                <div>
                  <div className="text-base font-bold text-accent-text">{won ? '通关！' : '真相揭晓'}</div>
                  <div className="text-xs text-fg-subtle">{won ? '已达成彩蛋通关条件，剧情进度单独展示'
                    : evaluation.scoreVersion ? '记录中被明确问清的事实，不代表已还原故事'
                    : '历史记录采用旧计分方式，不代表已确认事实'}</div>
                </div>
                <div className="ml-auto text-right">
                  <div className="text-xl font-bold text-accent-text">{evaluationDisplay.coverageValue}%</div>
                  <div className="text-[10px] text-fg-subtle">{evaluationDisplay.coverageLabel}</div>
                </div>
              </div>

              <div className="h-2 w-full rounded-full bg-border" role="progressbar"
                aria-label={evaluationDisplay.coverageLabel} aria-valuemin={0} aria-valuemax={100}
                aria-valuenow={evaluationDisplay.coverageValue ?? undefined}>
                <div
                  className="h-2 rounded-full bg-gradient-to-r from-accent to-accent-text transition-all"
                  style={{ width: `${evaluationDisplay.coverageValue ?? 0}%` }}
                />
              </div>

              <p className="text-sm text-fg-muted">还原程度：{evaluationDisplay.reconstructionLabel}</p>
              {evaluationDisplay.plotValue != null && (
                <p className="text-sm text-accent-text">剧情进度（非还原评分）：{evaluationDisplay.plotValue}%</p>
              )}

              <p className="text-sm leading-relaxed text-fg-muted">{evaluation.evaluation}</p>

              {evaluation.keyPointsCovered && evaluation.keyPointsCovered.length > 0 && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-success">
                    <CheckIcon className="h-3.5 w-3.5" /> {evaluation.scoreVersion ? '已确认的计分要点' : '旧记录中的已触及要点'}
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
                    <CloseIcon className="h-3.5 w-3.5" /> {evaluation.scoreVersion ? '尚未确认的计分要点' : '旧记录中的未触及要点'}
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
                  onClick={restart}
                  disabled={busy}
                  className="btn btn-accent"
                >
                  <RefreshIcon className="h-4 w-4" />
                  再来一局
                </button>
                <button
                  onClick={() => router.push('/')}
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
            <div className="shrink-0 border-t border-border/70 bg-surface/60 px-4 py-3 pb-[calc(5rem+env(safe-area-inset-bottom))] backdrop-blur-sm sm:pb-3">
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
                    disabled={!canAsk}
                    maxLength={500}
                    className="input flex-1 text-base"
                  />
                  <button
                    type="submit"
                    disabled={!canAsk || !question.trim()}
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
                const isFree = msg.isFreeReminder === true || chatMessages[i + 1]?.isFreeReminder === true;
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
