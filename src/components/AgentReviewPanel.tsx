'use client';

import { useEffect, useRef, useState } from 'react';
import { decodeFeedback, feedbackNeedsManualCorrection, type Feedback } from '@/lib/feedback-contract';
import { AgentReviewContractError, decodeAgentRunPage, decodeAgentStatus, decodeAgentStart,
  decodeCandidateDetail, decodeCandidateOperation, decodeRulePublication,
  type AgentRunPage, type AgentStatus, type CandidateDetail, type CandidateIntent } from '@/lib/agent-review-contract';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';
const ROOT = '/api/feedback/admin';
const validNote = (value: string) => !!value.trim() && Array.from(value).length <= 1000;
type Props = { token: string; feedbacks: Feedback[]; onFeedbackChanged: (feedback: Feedback) => void };
type PrivacyDraft = { feedbackId: string; rowVersion: number; question: string; host: string; claim: string; reason: string };
class HttpError extends Error { constructor(readonly status: number) { super(`操作未确认（${status}），请刷新核对`); } }

/** Each token owns a fresh mounted session; old responses/notes/nonces cannot cross it. */
export default function AgentReviewPanel(props: Props) {
  return props.token ? <PanelSession key={props.token} {...props} /> : null;
}
function usePrivateRequests(token: string) {
  const epoch = useRef(0), mounted = useRef(true), controllers = useRef(new Set<AbortController>());
  function reset() { epoch.current++; for (const controller of controllers.current) controller.abort(); controllers.current.clear(); }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; reset(); }; }, []);
  async function request(path: string, body?: string) {
    const generation = epoch.current, controller = new AbortController(); controllers.current.add(controller);
    const current = () => mounted.current && generation === epoch.current && !controller.signal.aborted;
    let expired = false, timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const pending = (async () => {
        const response = await fetch(API_BASE + path, { headers: { 'X-Admin-Token': token,
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
          ...(body !== undefined ? { method: 'POST', body } : {}), signal: controller.signal });
        if (!current()) return;
        if (!response.ok) throw new HttpError(response.status);
        const data: unknown = await response.json(); if (!current()) return;
        return { data, current };
      })();
      const deadline = new Promise<never>((_resolve, reject) => { timer = setTimeout(() => {
        expired = true; controller.abort(); reject(new Error('Acknowledgement timeout'));
      }, 30000); });
      return await Promise.race([pending, deadline]);
    } catch (error) { if (current() || (expired && mounted.current && generation === epoch.current)) throw error; }
    finally { clearTimeout(timer); controllers.current.delete(controller); }
  }
  return { request, reset };
}
type SavedIntent = { path: string; body: string; decode: (value: unknown) => unknown; candidateId?: string; started?: boolean };
function PanelSession({ token, feedbacks, onFeedbackChanged }: Props) {
  const { request, reset } = usePrivateRequests(token);
  const [runs, setRuns] = useState<AgentRunPage | null>(null), [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [status, setStatus] = useState<AgentStatus | null>(null), [selected, setSelected] = useState('');
  const [message, setMessage] = useState(''), [loading, setLoading] = useState(false), [busy, setBusy] = useState(false);
  const [intent, setIntent] = useState<SavedIntent | null>(null), [retryAllowed, setRetryAllowed] = useState(false);
  const [pollStopped, setPollStopped] = useState(false), [blocked, setBlocked] = useState(false);
  const [privacyDraft, setPrivacyDraft] = useState<PrivacyDraft | null>(null);
  const mutationLock = useRef<symbol | null>(null);
  function errorMessage(error: unknown) {
    if (error instanceof HttpError && error.status === 401) {
      setBlocked(true); setDetail(null); setRuns(null); setStatus(null); setIntent(null); reset();
      if (localStorage.getItem('turtle_admin_token') === token) {
        localStorage.removeItem('turtle_admin_token'); window.dispatchEvent(new Event('turtle-admin-token-changed'));
      }
      return '管理口令已失效，请重新登录';
    }
    if (error instanceof HttpError) {
      if ([401, 429, 503].includes(error.status)) setPollStopped(true);
      return error.status === 409 ? '版本或权限已变化，请刷新后重新核对，不会自动重试'
        : error.status === 429 ? '操作较频繁，已停止轮询，请稍后手动刷新'
        : error.status === 503 ? '此功能暂不可用（可能未启用任务或缺少已验证数据），不是空列表或成功'
        : error.message;
    }
    return error instanceof AgentReviewContractError ? error.message : '回复未能确认，可能已经提交；请刷新核对，或重试原操作';
  }
  function navigate() {
    reset(); mutationLock.current = null; setBusy(false); setIntent(null); setRetryAllowed(false);
    setDetail(null); setStatus(null); setPollStopped(false); setMessage(''); setLoading(true);
  }
  async function loadRuns(cursor: string | null = null) {
    navigate();
    try {
      const reply = await request(`${ROOT}/agent-runs?limit=50${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`);
      if (!reply?.current()) return;
      const page = decodeAgentRunPage(reply.data);
      setRuns(previous => cursor && previous ? { ...page, runs: [...previous.runs, ...page.runs] } : page);
      setLoading(false);
    } catch (error) { setLoading(false); setMessage(errorMessage(error)); }
  }
  async function loadDetail(candidate: string) {
    navigate();
    try {
      const reply = await request(`${ROOT}/rule-candidates/${candidate}`);
      if (!reply?.current()) return;
      setDetail(decodeCandidateDetail(reply.data, candidate)); setLoading(false);
    } catch (error) { setLoading(false); setMessage(errorMessage(error)); }
  }
  async function loadStatus(run: string, initial = false) {
    if (initial) navigate();
    try {
      const reply = await request(`${ROOT}/agent-runs/${run}`);
      if (!reply?.current()) return;
      setStatus(decodeAgentStatus(reply.data, run)); setLoading(false);
    } catch (error) { setLoading(false); setPollStopped(true); setMessage(errorMessage(error)); }
  }
  // Only one visible active run, one completed request at a time. Terminal/auth/rate stops it.
  useEffect(() => {
    if (!status || !['queued', 'running'].includes(status.state) || pollStopped || busy) return;
    let timer: ReturnType<typeof setTimeout> | undefined, inFlight = false, disposed = false;
    function schedule() {
      if (disposed || inFlight || timer !== undefined || document.visibilityState !== 'visible') return;
      timer = setTimeout(() => {
        timer = undefined;
        if (disposed || document.visibilityState !== 'visible') return;
        inFlight = true;
        void loadStatus(status!.id).finally(() => { inFlight = false; });
      }, 3000);
    }
    schedule();
    document.addEventListener('visibilitychange', schedule);
    return () => { disposed = true; clearTimeout(timer); document.removeEventListener('visibilitychange', schedule); };
    // loadStatus closes over the same token-owned session; status change schedules the next poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, pollStopped, busy]);
  async function send(saved: SavedIntent) {
    if (mutationLock.current || blocked) return;
    // Invalidate older reads before mutation: a pre-cancel poll is not current state.
    reset();
    const lock = Symbol('one-mutation'); mutationLock.current = lock; setBusy(true); setRetryAllowed(false); setIntent(saved); setMessage('');
    try {
      const reply = await request(saved.path, saved.body); if (!reply?.current()) return;
      const result = saved.decode(reply.data); setIntent(null); setMessage('操作凭证已核验；请以刷新后的实际状态为准');
      if (saved.candidateId) { await loadDetail(saved.candidateId); }
      else if (saved.started) { await loadStatus((result as { runId: string }).runId, true); }
      else if (saved.path.endsWith('/cancel')) { setStatus(result as AgentStatus); }
      else { setDetail(null); }
    } catch (error) {
      setRetryAllowed(!(error instanceof HttpError) && !(error instanceof AgentReviewContractError));
      setMessage(errorMessage(error));
    } finally { if (mutationLock.current === lock) { mutationLock.current = null; setBusy(false); } }
  }
  function candidateAction(action: CandidateIntent['action'], note = '', supported = false, independent = false) {
    if (!detail || intent || busy || !Number.isSafeInteger(detail.reviewVersion + 1)) return;
    if (action !== 'published' && !validNote(note)) return;
    if (action === 'approved' && (!supported || !independent || detail.availability !== 'ready' || detail.candidateStatus !== 'pending')) return;
    if (action === 'published' && (detail.availability !== 'ready' || detail.candidateStatus !== 'approved')) return;
    const operationKey = crypto.randomUUID(), expected = { candidateId: detail.candidateId, operationKey, action, previousVersion: detail.reviewVersion };
    const body = action === 'published' ? { operationKey, expectedReviewVersion: detail.reviewVersion, expectedProofDigest: detail.proofDigest,
      expectedRuleVersion: detail.activeRuleVersion, expectedPointerVersion: detail.activePointerVersion }
      : { operationKey, expectedReviewVersion: detail.reviewVersion, reviewNote: note,
        ...(action === 'approved' ? { expectedProofDigest: detail.proofDigest, answerSupported: true, contextIndependent: true } : {}) };
    void send({ path: `${ROOT}/rule-candidates/${detail.candidateId}/${action === 'approved' ? 'approve' : action === 'published' ? 'publish' : 'reject'}`,
      body: JSON.stringify(body), decode: value => decodeCandidateOperation(value, expected), candidateId: detail.candidateId });
  }
  function startTask(item: Feedback) {
    if (intent || busy || item.status !== 'approved' || !item.safeForModel || item.sourceState !== 'linked' || feedbackNeedsManualCorrection(item)) return;
    void send({ path: `${ROOT}/agent-runs`, body: JSON.stringify({ feedbackId: item.id, requestId: crypto.randomUUID(), expectedFeedbackVersion: item.rowVersion }),
      decode: decodeAgentStart, started: true });
  }
  function rollback(note: string, confirmed: boolean) {
    if (!detail?.material || !confirmed || !validNote(note) || intent || busy
      || detail.material.draft.baseRuleVersion === detail.activeRuleVersion || !Number.isSafeInteger(detail.activePointerVersion + 1)) return;
    const operationKey = crypto.randomUUID(), targetRuleVersion = detail.material.draft.baseRuleVersion;
    void send({ path: `${ROOT}/rule-releases/rollback`, body: JSON.stringify({ operationKey, targetRuleVersion,
      expectedRuleVersion: detail.activeRuleVersion, expectedPointerVersion: detail.activePointerVersion, reason: note }),
      decode: value => decodeRulePublication(value, { operationKey, targetRuleVersion, previousPointerVersion: detail.activePointerVersion }), candidateId: detail.candidateId });
  }
  const chosen = feedbacks.find(row => row.id === selected);
  if (blocked) return <section><p role="alert">{message}</p></section>;
  return <section className="card mt-6 space-y-4 p-4" aria-label="任务与候选管理">
    <h2 className="font-display text-lg font-bold">任务与候选管理</h2>
    <p className="muted text-sm">玩家说法与模型建议不是真相；回归通过不等于语义正确。批准、发布、回滚均须单独人工操作。</p>
    {message && <p role="alert" className="text-sm text-danger-strong">{message}</p>}
    <div className="flex flex-wrap gap-2">
      <button className="btn btn-ghost" disabled={loading} onClick={() => void loadRuns()}>刷新任务列表</button>
      {detail && <button className="btn btn-ghost" onClick={() => void loadDetail(detail.candidateId)}>刷新候选实际状态</button>}
      {intent && retryAllowed && <button className="btn btn-ghost" disabled={busy} onClick={() => void send(intent)}>重试原操作（相同请求）</button>}
    </div>
    {loading && <p role="status">正在核验…</p>}
    <label className="block">选择反馈<select className="input ml-2" value={selected} disabled={busy} onChange={event => {
      navigate(); setLoading(false); setSelected(event.target.value);
    }}><option value="">请选择</option>{feedbacks.map(item => <option key={item.id} value={item.id}>{item.soupTitle || item.soupId} · {item.question}</option>)}</select></label>
    {chosen && <PrivacyEditor key={`${chosen.id}:${chosen.rowVersion}`} token={token} item={chosen}
      draft={privacyDraft?.feedbackId === chosen.id && privacyDraft.rowVersion === chosen.rowVersion ? privacyDraft : null}
      onFeedbackChanged={(updated, draft) => { setPrivacyDraft(draft); onFeedbackChanged(updated); }}
      onStart={() => startTask(chosen)} disabled={busy || !!intent} />}
    {runs && <div><p>最近7天任务 · 此窗口已加载 {runs.runs.length} 条（不是用户人数）</p>
      {runs.runs.map(run => <article key={run.id} className="my-2 rounded border p-2">
        <p>任务 {run.id} · 原任务状态：{run.state} · 候选：{run.candidateStatus ?? '无'}</p>
        <p>模型尝试 {run.modelAttemptsUsed}/10 · 工具尝试 {run.toolAttemptsUsed}/8</p>
        <button className="btn btn-ghost" disabled={loading} onClick={() => void loadStatus(run.id, true)}>查看任务状态</button>
        {run.candidateId && <button className="btn btn-ghost" disabled={loading} onClick={() => void loadDetail(run.candidateId!)}>查看候选</button>}
      </article>)}
      {runs.nextCursor && <button className="btn btn-ghost" disabled={loading} onClick={() => void loadRuns(runs.nextCursor)}>加载更多任务</button>}
    </div>}
    {status && <div><p>原任务状态：{status.state} · 模型 {status.modelAttemptsUsed}/10 · 工具 {status.toolAttemptsUsed}/8</p>
      {status.reason && <p>停止原因：{status.reason}</p>}
      {status.steps.map(step => <p key={step.seq}>步骤 {step.seq} · {step.action} · {step.tool} · {step.state}</p>)}
      {['queued', 'running'].includes(status.state) && <button className="btn btn-ghost" disabled={busy || !!intent} onClick={() => void send({
        path: `${ROOT}/agent-runs/${status.id}/cancel`, body: JSON.stringify({ expectedRowVersion: status.rowVersion }),
        decode: value => { const result = decodeAgentStatus(value, status.id);
          if (result.state !== 'cancelled' || result.rowVersion !== status.rowVersion + 1) throw new AgentReviewContractError(); return result; } })}>取消当前任务</button>}
      {status.candidateId && <button className="btn btn-ghost" onClick={() => void loadDetail(status.candidateId!)}>查看候选</button>}
    </div>}
    {detail && <CandidateCard key={`${detail.candidateId}:${detail.reviewVersion}:${detail.activePointerVersion}`} detail={detail}
      disabled={busy || !!intent} onAction={candidateAction} onRollback={rollback} />}
  </section>;
}

function PrivacyEditor({ token, item, draft, onFeedbackChanged, onStart, disabled }: {
  token: string; item: Feedback; draft: PrivacyDraft | null;
  onFeedbackChanged: (feedback: Feedback, draft: PrivacyDraft | null) => void; onStart: () => void; disabled: boolean;
}) {
  const { request } = usePrivateRequests(token), lock = useRef(false);
  const [question, setQuestion] = useState(draft?.question ?? item.question), [host, setHost] = useState(draft?.host ?? item.hostAnswer);
  const [claim, setClaim] = useState(draft?.claim ?? item.expectedAnswer), [reason, setReason] = useState(draft?.reason ?? item.reason ?? '');
  const [note, setNote] = useState(''), [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  async function save(safe: boolean) {
    if (lock.current || disabled || !validNote(note) || !Number.isSafeInteger(item.rowVersion + 1)
      || (safe && (!confirmed || !question.trim() || !host.trim() || !claim.trim()))) return;
    lock.current = true; setBusy(true); setMessage('');
    try {
      const reply = await request(`${ROOT}/${item.id}/privacy`, JSON.stringify({ expectedRowVersion: item.rowVersion,
        safeForModel: safe, reviewedForPrivacy: safe && confirmed, reviewNote: note,
        ...(safe ? { sanitizedQuestion: question, sanitizedHostAnswer: host, sanitizedExpectedClaim: claim, sanitizedReason: reason || null } : {}) }));
      if (!reply?.current()) return;
      if (!reply.data || typeof reply.data !== 'object' || Array.isArray(reply.data)) throw new AgentReviewContractError();
      const body = reply.data as Record<string, unknown>;
      if (body.ok !== true || Object.keys(body).sort().join(',') !== 'feedback,ok') throw new AgentReviewContractError();
      const updated = decodeFeedback(body.feedback);
      if (updated.id !== item.id || updated.rowVersion !== item.rowVersion + 1 || updated.safeForModel !== safe || updated.status !== item.status) throw new AgentReviewContractError();
      // Retain only this session's submitted draft at the verified acknowledgement version.
      // It is not a server read-back proof and never supplies task/execution authority.
      onFeedbackChanged(updated, safe ? { feedbackId: item.id, rowVersion: updated.rowVersion, question, host, claim, reason } : null);
      setConfirmed(false); setNote(''); setMessage('隐私授权已核验，没有自动启动任务');
    } catch (error) { setMessage(error instanceof HttpError ? error.message : '授权回复未确认，可能已提交；请刷新反馈后重新核对'); }
    finally { lock.current = false; setBusy(false); }
  }
  const canStart = item.status === 'approved' && item.safeForModel && item.sourceState === 'linked' && !feedbackNeedsManualCorrection(item);
  const inputs: Array<[string, string, (value: string) => void, number]> = [
    ['脱敏后的问题', question, setQuestion, 500], ['脱敏后的主持人回答', host, setHost, 100],
    ['脱敏后的玩家说法（非真相）', claim, setClaim, 100], ['脱敏后的反馈背景', reason, setReason, 2000], ['隐私审核理由', note, setNote, 1000]];
  return <div className="space-y-2 rounded border p-3">
    <h3>隐私审核与任务启动</h3><p>反馈版本：{item.rowVersion} · 原审批：{item.status} · 模型许可：{item.safeForModel ? '已授权' : '未授权'}</p>
    <p className="muted text-sm">逐项编辑脱敏内容；不要填写身份、密钥。隐私授权不等于答案正确，仍需已批准且关联真实轮次才能启动。</p>
    <p className="muted text-sm">{draft ? '下方保留本次已确认提交的草稿，不是服务器回读证明。' : '下方为从原始反馈预填的待审核草稿，不代表已保存的脱敏版本。'} 编辑不会自动保存；任务使用服务器已保存版本，候选材料展示实际冻结输入。</p>
    {inputs.map(([label, value, set, max]) => <label className="block" key={label}>{label}
      <textarea className="input block w-full" value={value} maxLength={max * 2} onChange={event => set(event.target.value)} /></label>)}
    <label className="block"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />已逐项检查隐私与脱敏内容</label>
    <button className="btn btn-ghost" disabled={disabled || busy || !confirmed || !validNote(note) || !question.trim() || !host.trim() || !claim.trim()
      || Array.from(question).length > 500 || Array.from(host).length > 100 || Array.from(claim).length > 100 || Array.from(reason).length > 2000}
      onClick={() => void save(true)}>保存脱敏授权（不启动任务）</button>
    <button className="btn btn-ghost" disabled={disabled || busy || !validNote(note)} onClick={() => void save(false)}>撤销模型许可</button>
    <button className="btn btn-accent" disabled={disabled || busy || !canStart} onClick={onStart}>显式启动修复任务</button>
    {message && <p role="alert">{message}</p>}
  </div>;
}
function CandidateCard({ detail, disabled, onAction, onRollback }: { detail: CandidateDetail; disabled: boolean;
  onAction: (action: CandidateIntent['action'], note?: string, supported?: boolean, independent?: boolean) => void;
  onRollback: (note: string, confirmed: boolean) => void }) {
  const [supported, setSupported] = useState(false), [independent, setIndependent] = useState(false), [note, setNote] = useState('');
  const [rollbackNote, setRollbackNote] = useState(''), [rollbackConfirmed, setRollbackConfirmed] = useState(false);
  const material = detail.material, ready = detail.availability === 'ready';
  return <article className="space-y-3 rounded border p-3" aria-label="候选审核">
    <h3>候选工作流：{detail.candidateStatus} · 审核版本：{detail.reviewVersion}</h3>
    <p>原任务结果：{detail.agentStatus.state}（人工审核不会重写原任务） · 材料：{detail.availability}</p>
    <p className="break-all">当前规则：{detail.activeRuleVersion} · 指针版本：{detail.activePointerVersion}</p>
    {detail.blockers.map(code => <p key={code}>{code} · 不提供新的批准/发布权限</p>)}
    {detail.blockers.includes('candidate_context_unavailable') && <p>原始对话缺失、不完整或过大，需人工处理；不能把缺材料当成空上下文批准。</p>}
    {detail.publishedRuleVersion && <p className="break-all">历史发布版本：{detail.publishedRuleVersion}（不代表当前仍生效）</p>}
    {material && <>
      <h4>原始提问与之前对话（仅人工核对）</h4>
      <p className="muted text-sm">来自实际关联记录，不是玩家理由或模型总结；这些额外原文未加入修复 Agent 的模型输入。请同时核对下面的脱敏输入。</p>
      <dl><dt>原始问题</dt><dd className="whitespace-pre-wrap break-words">{material.sourceContext.originalQuestion}</dd>
        <dt>原主持回复</dt><dd className="whitespace-pre-wrap break-words">{material.sourceContext.originalHostAnswer}</dd></dl>
      {material.sourceContext.messages.length === 0 ? <p>已核验：这次提问之前没有对话。</p>
        : material.sourceContext.messages.map(message => <div key={message.messageId}>
          <p>{message.role === 'user' ? '玩家' : '主持'} · 原始前文</p><p className="whitespace-pre-wrap break-words">{message.content}</p></div>)}
      <p className="break-all">原始上下文摘要：{material.sourceContext.contextDigest}</p>
      <h4>玩家说法（不是标准答案）</h4>
      <dl>{Object.entries(material.sanitizedInput).map(([key, value]) => <div key={key}><dt>{key}</dt><dd className="whitespace-pre-wrap break-words">{value ?? '无'}</dd></div>)}</dl>
      <h4>实际程序诊断</h4><pre className="whitespace-pre-wrap break-all">{JSON.stringify(material.programDiagnostic, null, 2)}</pre>
      <h4>模型建议（不是人工确认）</h4><p>{material.draft.question} → {material.draft.answer} · {material.draft.operation}</p>
      <p className="whitespace-pre-wrap break-words">{material.draft.evidenceSummary}</p>
      {material.oldTarget && <div><h4>真实旧目标 → 新答案</h4><p>{material.oldTarget.question}：{material.oldTarget.answer} → {material.draft.answer}</p>
        <p className="break-all">{material.oldTarget.type} · {material.oldTarget.sourcePath} · {material.oldTarget.targetRuleDigest}</p></div>}
      <h4>完整事实与限定条件（不得仅凭模型摘要批准）</h4>
      {material.factScope.map(fact => <div key={fact.id} className={`rounded border p-2 ${material.highlightedFactIds.includes(fact.id) ? 'border-accent' : ''}`}>
        <p className="break-all">{fact.category} · {fact.sourcePath} · {fact.id}</p><pre className="whitespace-pre-wrap break-words">{fact.payload}</pre></div>)}
      <h4>完整回归报告（机械检查 ≠ 语义正确）</h4>
      <p>{material.report.evidenceKind === 'synthetic_fixture' ? '合成测试证据，不是真实模型/真人人审成绩' : '确定性回归证据，仍需人工核对语义'}</p>
      <p>{material.report.status} · 计划 {material.report.inputCaseCount} · 尝试 {material.report.attemptedCaseCount} · 通过 {material.report.passedCaseCount}
        · 清理 {String(material.report.cleanupConfirmed)} · 截断 {String(material.report.truncated)} · 用时 {material.report.elapsedSeconds}s</p>
      {material.report.caseResults.map(row => <p key={row.caseId} className="break-all">{row.caseId} · {row.suite} · {row.code} · {row.passed ? '通过' : '未通过'}</p>)}
      <pre className="whitespace-pre-wrap break-all">{JSON.stringify({ reportId: material.report.reportId, candidateDraftDigest: material.report.draftDigest,
        suiteManifestDigest: material.report.suiteManifestDigest, contextDigest: material.report.contextDigest, proofDigest: detail.proofDigest }, null, 2)}</pre>
    </>}
    {detail.review && <div><h4>保存的人工审核历史（不会自动勾选新确认）</h4><p className="whitespace-pre-wrap break-words">{detail.review.reviewNote}</p>
      <pre className="whitespace-pre-wrap break-all">{JSON.stringify(detail.review, null, 2)}</pre></div>}
    {['pending', 'approved'].includes(detail.candidateStatus) && <>
      <label className="block">候选审核理由<textarea className="input block w-full" value={note} onChange={event => setNote(event.target.value)} /></label>
      <p className="muted text-sm">1–1000字符，勿粘贴身份、密钥；此备注是私有记录，不是自动脱敏保证。</p>
      {ready && detail.candidateStatus === 'pending' && <>
        <label className="block"><input type="checkbox" checked={supported} onChange={event => setSupported(event.target.checked)} />答案有完整事实支持</label>
        <label className="block"><input type="checkbox" checked={independent} onChange={event => setIndependent(event.target.checked)} />不依赖玩家当前上下文</label>
        <button className="btn btn-accent" disabled={disabled || !supported || !independent || !validNote(note)}
          onClick={() => onAction('approved', note, supported, independent)}>批准候选（不发布）</button>
      </>}
      <button className="btn btn-ghost" disabled={disabled || !validNote(note)} onClick={() => onAction('rejected', note)}>拒绝候选</button>
    </>}
    {ready && detail.candidateStatus === 'approved' && <button className="btn btn-accent" disabled={disabled} onClick={() => onAction('published')}>单独确认发布</button>}
    {material && material.draft.baseRuleVersion !== detail.activeRuleVersion && <div className="space-y-2">
      <h4>回滚到此候选已核验的原始规则版本（不会删除历史）</h4><p className="break-all">目标：{material.draft.baseRuleVersion}</p>
      <label className="block">回滚理由<textarea className="input block w-full" value={rollbackNote} onChange={event => setRollbackNote(event.target.value)} /></label>
      <label className="block"><input type="checkbox" checked={rollbackConfirmed} onChange={event => setRollbackConfirmed(event.target.checked)} />确认目标与当前指针，回滚仅影响新会话</label>
      <button className="btn btn-ghost" disabled={disabled || !rollbackConfirmed || !validNote(rollbackNote)} onClick={() => onRollback(rollbackNote, rollbackConfirmed)}>确认回滚</button>
    </div>}
  </article>;
}
