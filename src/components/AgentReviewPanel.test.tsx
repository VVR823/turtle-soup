import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import AgentReviewPanel from './AgentReviewPanel';
import { decodeFeedback } from '../lib/feedback-contract';
import { agentStatus, candidateDetail, candidateId, reviewState, runId, reportId, nextRule } from '../../tests/frontend/agent-review-fixtures';

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const feedback = () => decodeFeedback({ id: reportId, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: '合成测试汤',
  question: '他知道吗？', hostAnswer: '不是', expectedAnswer: '是', reason: null, status: 'approved',
  reviewedAt: '2026-10-09T00:00:01Z', mergedAt: null, mergedAnswer: null, rowVersion: 2,
  safeForModel: false, sourceState: 'linked', turnId: runId });
const runPage = () => ({ schemaVersion: 1, nextCursor: null, runs: [{ id: runId, feedbackId: reportId,
  state: 'awaiting_review', rowVersion: 9, createdAt: 0, deadlineAt: 180, modelAttemptsUsed: 3, toolAttemptsUsed: 2,
  candidateId, candidateStatus: 'pending' }] });
async function openCandidate() {
  fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看候选' }));
  await screen.findByText('模型建议，不是真人确认。');
}
test('original conversation is displayed before human context-independence confirmation', async () => {
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('rule-candidates') ? candidateDetail() : runPage()));
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  await openCandidate();
  expect(screen.getByRole('heading', { name: '原始提问与之前对话（仅人工核对）' })).toBeTruthy();
  expect(screen.getByText('原本他指的是小明吗？')).toBeTruthy();
  expect(screen.getByText('刚才说的是小明吗？')).toBeTruthy();
  expect((screen.getByLabelText('不依赖玩家当前上下文') as HTMLInputElement).checked).toBe(false);
});
// Real component, controlled HTTP only: breaks are automatic permissions/publication,
// stale private content/confirmation reuse, new nonces after uncertain commits or double-clicks.
test('full facts appear before unchecked semantic confirmations; approval never auto-publishes', async () => {
  const posts: Array<{ url: string; body: Record<string, unknown> }> = []; let approved = false;
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body)); posts.push({ url, body }); approved = true;
      return response({ schemaVersion: 1, candidateId, operationKey: body.operationKey, action: 'approved',
        reviewVersion: 1, candidateStatus: 'approved', publishedRuleVersion: null });
    }
    return response(url.includes('rule-candidates') ? approved
      ? { ...candidateDetail(), candidateStatus: 'approved', reviewVersion: 1, review: reviewState() }
      : candidateDetail() : runPage());
  });
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  await openCandidate();
  expect(screen.getByText('{"text":"可能知道，但仅限事后","confidence":"low"}')).toBeTruthy();
  const supported = screen.getByLabelText('答案有完整事实支持') as HTMLInputElement;
  const context = screen.getByLabelText('不依赖玩家当前上下文') as HTMLInputElement;
  expect(supported.checked).toBe(false); expect(context.checked).toBe(false);
  const approve = screen.getByRole('button', { name: '批准候选（不发布）' });
  expect(approve.hasAttribute('disabled')).toBe(true);
  fireEvent.click(supported); fireEvent.click(context);
  fireEvent.change(screen.getByLabelText('候选审核理由'), { target: { value: '核对完整事实与限定条件' } });
  fireEvent.click(approve); fireEvent.click(approve);
  await screen.findByRole('button', { name: '单独确认发布' });
  expect(posts).toHaveLength(1); expect(posts[0].url.endsWith('/approve')).toBe(true);
  expect(posts[0].body).toMatchObject({ expectedReviewVersion: 0, answerSupported: true, contextIndependent: true });
  expect(Object.keys(posts[0].body).sort()).toEqual(['answerSupported', 'contextIndependent', 'expectedProofDigest', 'expectedReviewVersion', 'operationKey', 'reviewNote']);
});
test('late detail from the old admin cannot restore facts, checks or reasons after token change', async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal('fetch', async (url: string) => url.includes('rule-candidates')
    ? new Promise<Response>(done => { resolve = done; }) : response(runPage()));
  const page = render(<AgentReviewPanel token="synthetic-old" feedbacks={[]} onFeedbackChanged={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看候选' }));
  await waitFor(() => expect(resolve).toBeTypeOf('function'));
  page.rerender(<AgentReviewPanel token="synthetic-new" feedbacks={[]} onFeedbackChanged={() => {}} />);
  await act(async () => { resolve(response(candidateDetail())); });
  expect(screen.queryByText('模型建议，不是真人确认。')).toBeNull();
  expect(screen.queryByLabelText('答案有完整事实支持')).toBeNull();
});
test('uncertain committed response offers only exact original intent retry, never new automatic mutation', async () => {
  const bodies: string[] = []; let first = true;
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      bodies.push(String(init.body)); if (first) { first = false; throw new Error('reply lost after commit'); }
      const body = JSON.parse(String(init.body));
      return response({ schemaVersion: 1, candidateId, operationKey: body.operationKey, action: 'rejected',
        reviewVersion: 1, candidateStatus: 'rejected', publishedRuleVersion: null });
    }
    return response(url.includes('rule-candidates') ? candidateDetail() : runPage());
  });
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  await openCandidate(); fireEvent.change(screen.getByLabelText('候选审核理由'), { target: { value: '事实不充分' } });
  fireEvent.click(screen.getByRole('button', { name: '拒绝候选' }));
  await screen.findByText(/可能已经提交/); expect(bodies).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: '重试原操作（相同请求）' }));
  await waitFor(() => expect(bodies).toHaveLength(2)); expect(bodies[1]).toBe(bodies[0]);
});
test('manual privacy review saves edited claims with actual CAS, without starting a model task', async () => {
  const f = feedback(); let body: Record<string, unknown> | undefined; const changed = vi.fn();
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    body = JSON.parse(String(init?.body)); return response({ ok: true, feedback: { ...f, safeForModel: true, rowVersion: 3 } });
  });
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[f]} onFeedbackChanged={changed} />);
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: f.id } });
  const save = screen.getByRole('button', { name: '保存脱敏授权（不启动任务）' });
  expect(save.hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByLabelText('脱敏后的问题'), { target: { value: '事后他知道吗？' } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '已移除身份信息' } });
  fireEvent.click(screen.getByLabelText('已逐项检查隐私与脱敏内容'));
  fireEvent.click(save); await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(body).toMatchObject({ expectedRowVersion: 2, safeForModel: true, reviewedForPrivacy: true,
    sanitizedQuestion: '事后他知道吗？', sanitizedHostAnswer: '不是', sanitizedExpectedClaim: '是', sanitizedReason: null });
  expect(screen.getByRole('button', { name: '显式启动修复任务' }).hasAttribute('disabled')).toBe(true);
});
test('unsafe, unlinked or unapproved feedback never enables task start', () => {
  const f = { ...feedback(), safeForModel: true, sourceState: 'legacy' as const };
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[f]} onFeedbackChanged={() => {}} />);
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: f.id } });
  expect(screen.getByRole('button', { name: '显式启动修复任务' }).hasAttribute('disabled')).toBe(true);
});

test.each(['version', 'token'] as const)('acknowledged privacy draft cannot cross a changed %s', async kind => {
  const f = { ...feedback(), reason: '原始背景' }, changed = vi.fn();
  const updated = { ...f, rowVersion: 3, safeForModel: true };
  vi.stubGlobal('fetch', async () => response({ ok: true, feedback: updated }));
  const view = render(<AgentReviewPanel token="draft-owner" feedbacks={[f]} onFeedbackChanged={changed} />);
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: f.id } });
  fireEvent.change(screen.getByLabelText('脱敏后的问题'), { target: { value: '本会话脱敏问题' } });
  fireEvent.change(screen.getByLabelText('脱敏后的反馈背景'), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '核对隐私' } });
  fireEvent.click(screen.getByLabelText('已逐项检查隐私与脱敏内容'));
  fireEvent.click(screen.getByRole('button', { name: '保存脱敏授权（不启动任务）' }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  view.rerender(<AgentReviewPanel token="draft-owner" feedbacks={[updated]} onFeedbackChanged={changed} />);
  expect((screen.getByLabelText('脱敏后的问题') as HTMLTextAreaElement).value).toBe('本会话脱敏问题');
  expect((screen.getByLabelText('脱敏后的反馈背景') as HTMLTextAreaElement).value).toBe('');
  view.rerender(<AgentReviewPanel token={kind === 'token' ? 'different-owner' : 'draft-owner'}
    feedbacks={[{ ...updated, rowVersion: kind === 'version' ? 4 : 3 }]} onFeedbackChanged={changed} />);
  if (kind === 'token') fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: f.id } });
  expect((screen.getByLabelText('脱敏后的问题') as HTMLTextAreaElement).value).toBe('他知道吗？');
  expect((screen.getByLabelText('脱敏后的反馈背景') as HTMLTextAreaElement).value).toBe('原始背景');
  expect((screen.getByLabelText('已逐项检查隐私与脱敏内容') as HTMLInputElement).checked).toBe(false);
  expect((screen.getByLabelText('隐私审核理由') as HTMLTextAreaElement).value).toBe('');
  expect(changed).toHaveBeenCalledTimes(1);
});
test.each(['terminal', 'unavailable'])('foreground resumes one active GET and preserves %s stop', async outcome => {
  let visibility: DocumentVisibilityState = 'visible';
  const visibilitySpy = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
  const running = { ...agentStatus(), state: 'running', candidateId: null, steps: [] };
  let reads = 0, posts = 0, complete!: (value: Response) => void;
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { posts++; return response({}); }
    if (!url.endsWith('/' + runId)) return response(runPage());
    if (++reads === 1) return response(running);
    return new Promise<Response>(done => { complete = done; });
  });
  const page = render(<AgentReviewPanel token="synthetic-foreground" feedbacks={[]} onFeedbackChanged={() => {}} />);
  try {
    fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
    const view = await screen.findByRole('button', { name: '查看任务状态' });
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(view); });
    expect(reads).toBe(1);
    visibility = 'hidden';
    await act(async () => { fireEvent(document, new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(3000); });
    expect(reads).toBe(1);
    visibility = 'visible';
    await act(async () => {
      fireEvent(document, new Event('visibilitychange')); fireEvent(document, new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(reads).toBe(2);
    expect(complete).toBeTypeOf('function');
    await act(async () => {
      fireEvent(document, new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(3000);
    });
    expect(reads).toBe(2); // An unresolved status read must not get another observer.
    await act(async () => { complete(outcome === 'terminal'
      ? response({ ...running, state: 'failed', reason: 'model_unavailable' }) : response({}, 503)); });
    expect(screen.getByText(outcome === 'terminal' ? /原任务状态：failed/ : /此功能暂不可用/)).toBeTruthy();
    await act(async () => {
      visibility = 'hidden'; fireEvent(document, new Event('visibilitychange'));
      visibility = 'visible'; fireEvent(document, new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(reads).toBe(2); expect(posts).toBe(0);
    page.unmount();
    await act(async () => { fireEvent(document, new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(6000); });
    expect(reads).toBe(2);
  } finally { page.unmount(); vi.useRealTimers(); visibilitySpy.mockRestore(); }
});

test('a cancelled task cannot be restored by a late older status poll', async () => {
  let late!: (value: Response) => void; let reads = 0;
  const running = { ...agentStatus(), state: 'running', candidateId: null, steps: [] };
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return response({ ...running, state: 'cancelled', rowVersion: 10, reason: 'cancellation' });
    if (!url.endsWith('/' + runId)) return response(runPage());
    if (++reads === 1) return response(running);
    return new Promise<Response>(done => { late = done; });
  });
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  const view = await screen.findByRole('button', { name: '查看任务状态' });
  vi.useFakeTimers();
  try {
    await act(async () => { fireEvent.click(view); });
    expect(screen.getByRole('button', { name: '取消当前任务' })).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(late).toBeTypeOf('function');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '取消当前任务' })); });
    expect(screen.getByText(/原任务状态：cancelled/)).toBeTruthy();
    await act(async () => { late(response(running)); });
    expect(screen.getByText(/原任务状态：cancelled/)).toBeTruthy();
  } finally { vi.useRealTimers(); }
});
test('a hanging mutation times out with an uncertain result and retains the exact original intent', async () => {
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => init?.method === 'POST'
    ? new Promise<Response>(() => {}) : response(url.includes('rule-candidates') ? candidateDetail() : runPage()));
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  await openCandidate(); fireEvent.change(screen.getByLabelText('候选审核理由'), { target: { value: '不支持' } });
  vi.useFakeTimers();
  try {
    fireEvent.click(screen.getByRole('button', { name: '拒绝候选' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(30001); });
    expect(screen.getByText(/可能已经提交/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试原操作（相同请求）' }).hasAttribute('disabled')).toBe(false);
  } finally { vi.useRealTimers(); }
});
test.each(['list', 'approve', 'publish'] as const)('late old-token %s cannot restore private state or an operation nonce', async kind => {
  let resolve!: (value: Response) => void; let oldBody: Record<string, unknown> = {};
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (kind === 'list' || init?.method === 'POST') {
      if (init?.body) oldBody = JSON.parse(String(init.body));
      return new Promise<Response>(done => { resolve = done; });
    }
    return response(url.includes('rule-candidates') ? kind === 'publish'
      ? { ...candidateDetail(), candidateStatus: 'approved', reviewVersion: 1, review: reviewState() }
      : candidateDetail() : runPage());
  });
  const view = render(<AgentReviewPanel token="old-private-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  if (kind === 'list') fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  else {
    await openCandidate();
    if (kind === 'approve') {
      fireEvent.change(screen.getByLabelText('候选审核理由'), { target: { value: 'Old private note' } });
      fireEvent.click(screen.getByLabelText('答案有完整事实支持')); fireEvent.click(screen.getByLabelText('不依赖玩家当前上下文'));
      fireEvent.click(screen.getByRole('button', { name: '批准候选（不发布）' }));
    } else fireEvent.click(screen.getByRole('button', { name: '单独确认发布' }));
  }
  await waitFor(() => expect(resolve).toBeTypeOf('function'));
  view.rerender(<AgentReviewPanel token="new-private-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  await act(async () => { resolve(response(kind === 'list' ? runPage() : { schemaVersion: 1, candidateId,
    operationKey: oldBody.operationKey, action: kind === 'approve' ? 'approved' : 'published', reviewVersion: kind === 'approve' ? 1 : 2,
    candidateStatus: kind === 'approve' ? 'approved' : 'published', publishedRuleVersion: kind === 'approve' ? null : nextRule })); });
  expect(screen.queryByText(/Old private note/)).toBeNull();
  expect(screen.queryByRole('article')).toBeNull();
  expect(screen.queryByRole('button', { name: '重试原操作（相同请求）' })).toBeNull();
  expect(screen.queryByText(/操作凭证已核验/)).toBeNull();
});
test('missing corpus stays unavailable and offers only a separate rejection, not invented evidence or approval', async () => {
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('rule-candidates') ? { ...candidateDetail(),
    availability: 'unavailable', blockers: ['candidate_corpus_missing'], material: null, proofDigest: null } : runPage()));
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[]} onFeedbackChanged={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看候选' }));
  await screen.findByText(/candidate_corpus_missing/);
  expect(screen.queryByLabelText('答案有完整事实支持')).toBeNull();
  expect(screen.queryByRole('button', { name: '单独确认发布' })).toBeNull();
  expect(screen.getByRole('button', { name: '拒绝候选' }).hasAttribute('disabled')).toBe(true);
});
test.each([' \t\u3000 ', '界'.repeat(1001)])('invalid candidate reason never enables a fresh mutation %#', async note => {
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('rule-candidates') ? candidateDetail() : runPage()));
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={[]} onFeedbackChanged={() => {}} />); await openCandidate();
  fireEvent.click(screen.getByLabelText('答案有完整事实支持')); fireEvent.click(screen.getByLabelText('不依赖玩家当前上下文'));
  fireEvent.change(screen.getByLabelText('候选审核理由'), { target: { value: note } });
  expect(screen.getByRole('button', { name: '批准候选（不发布）' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: '拒绝候选' }).hasAttribute('disabled')).toBe(true);
});
