import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import AgentReviewPanel from './AgentReviewPanel';
import { decodeFeedback } from '@/lib/feedback-contract';
import { agentStatus, candidateDetail, candidateId, runId, reportId, rule, nextRule, reviewState, factId } from '../../tests/frontend/agent-review-fixtures';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const row = () => decodeFeedback({ id: reportId, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: null,
  question: '合成问题', hostAnswer: '不是', expectedAnswer: '是', reason: null, status: 'approved',
  reviewedAt: '2026-10-09T00:00:01Z', mergedAt: null, mergedAnswer: null, rowVersion: 2,
  safeForModel: true, sourceState: 'linked', turnId: runId });
const runs = () => ({ schemaVersion: 1, nextCursor: null, runs: [{ id: runId, feedbackId: reportId, state: 'awaiting_review',
  rowVersion: 9, createdAt: 0, deadlineAt: 180, modelAttemptsUsed: 3, toolAttemptsUsed: 2, candidateId, candidateStatus: 'pending' }] });
const renderPanel = (feedbacks = [] as ReturnType<typeof row>[], changed = vi.fn()) =>
  render(<AgentReviewPanel token="synthetic-admin" feedbacks={feedbacks} onFeedbackChanged={changed} />);
async function openCandidate() {
  fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看候选' }));
  await screen.findByRole('article', { name: '候选审核' });
}

test('an empty admin token mounts no private controls and makes no request', () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  render(<AgentReviewPanel token="" feedbacks={[]} onFeedbackChanged={vi.fn()} />);
  expect(screen.queryByRole('region')).toBeNull(); expect(screen.queryByRole('button')).toBeNull(); expect(fetch).not.toHaveBeenCalled();
});

test.each(['synthetic-admin', 'new-admin'])('401 blocks private controls but only clears the matching stored credential: %s', async stored => {
  localStorage.setItem('turtle_admin_token', stored);
  vi.stubGlobal('fetch', async () => response({ detail: 'PRIVATE' }, 401));
  const event = vi.fn(); window.addEventListener('turtle-admin-token-changed', event);
  try {
    renderPanel(); fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
    await screen.findByText('管理口令已失效，请重新登录');
    expect(screen.queryByRole('button', { name: '刷新任务列表' })).toBeNull();
    expect(localStorage.getItem('turtle_admin_token')).toBe(stored === 'synthetic-admin' ? null : stored);
    expect(event).toHaveBeenCalledTimes(stored === 'synthetic-admin' ? 1 : 0);
  } finally { window.removeEventListener('turtle-admin-token-changed', event); }
});

test.each([{ status: 409, text: '版本或权限已变化' }, { status: 429, text: '已停止轮询' },
  { status: 503, text: '此功能暂不可用' }, { status: 500, text: '操作未确认（500）' }])(
  'list HTTP $status is explicit failure, not an empty success', async ({ status, text }) => {
    vi.stubGlobal('fetch', async () => response({ detail: 'PRIVATE' }, status)); renderPanel();
    fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
    const alert = await screen.findByRole('alert'); expect(alert.textContent).toContain(text);
    expect(alert.textContent).not.toContain('PRIVATE'); expect(screen.queryByText(/此窗口已加载/)).toBeNull();
  },
);

test('task pagination appends distinct summaries and preserves cursor ownership', async () => {
  const first = { ...runs(), nextCursor: 'owned_cursor' };
  const second = runs(); second.runs[0] = { ...second.runs[0], id: reportId };
  const urls: string[] = []; vi.stubGlobal('fetch', async (url: string) => { urls.push(url); return response(url.includes('cursor=') ? second : first); });
  renderPanel(); fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '加载更多任务' }));
  await screen.findByText(/此窗口已加载 2 条/);
  expect(urls[1]).toContain('limit=50&cursor=owned_cursor'); expect(screen.getAllByRole('button', { name: '查看任务状态' })).toHaveLength(2);
});

test.each([{ state: 'cancelled', version: 10, accepted: true }, { state: 'cancelled', version: 11, accepted: false },
  { state: 'running', version: 10, accepted: false }])('cancel acknowledgement requires exact state/version: $state/$version', async ({ state, version, accepted }) => {
  const running = { ...agentStatus(), state: 'running', candidateId: null, steps: [] };
  const posts: RequestInit[] = [];
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { posts.push(init); return response({ ...running, state, rowVersion: version }); }
    return response(url.endsWith('/' + runId) ? running : runs());
  });
  renderPanel(); fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看任务状态' }));
  fireEvent.click(await screen.findByRole('button', { name: '取消当前任务' }));
  if (accepted) { await screen.findByText(/操作凭证已核验/); expect(screen.queryByRole('button', { name: '取消当前任务' })).toBeNull(); }
  else { await screen.findByText(/任务数据暂时无法核验/); expect(screen.queryByText(/操作凭证已核验/)).toBeNull(); }
  expect(posts).toHaveLength(1); expect(JSON.parse(String(posts[0].body))).toEqual({ expectedRowVersion: 9 });
});

test('viewing a task status can open its bound candidate', async () => {
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('rule-candidates') ? candidateDetail() : url.endsWith('/' + runId) ? agentStatus() : runs()));
  renderPanel(); fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看任务状态' }));
  await screen.findByText(/原任务状态：awaiting_review · 模型/);
  fireEvent.click(screen.getAllByRole('button', { name: '查看候选' }).at(-1)!);
  await screen.findByRole('article', { name: '候选审核' });
});

test.each([null, [], { ok: false }, { ok: true, feedback: row(), extra: true },
  { ok: true, feedback: { ...row(), id: runId, rowVersion: 3, safeForModel: false } },
  { ok: true, feedback: { ...row(), rowVersion: 4, safeForModel: false } },
  { ok: true, feedback: { ...row(), rowVersion: 3, safeForModel: true } },
  { ok: true, feedback: { ...row(), rowVersion: 3, safeForModel: false, status: 'rejected' } }])(
  'unconfirmed privacy revocation cannot update the parent row %#', async body => {
    const changed = vi.fn(); vi.stubGlobal('fetch', async () => response(body)); renderPanel([row()], changed);
    fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: reportId } });
    fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '合成撤销理由' } });
    fireEvent.click(screen.getByRole('button', { name: '撤销模型许可' }));
    await screen.findByText(/授权回复未确认/); expect(changed).not.toHaveBeenCalled();
  },
);

test('privacy revocation sends only the revocation intent and preserves the approved answer status', async () => {
  const changed = vi.fn(); let body: unknown;
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    body = JSON.parse(String(init?.body)); return response({ ok: true, feedback: { ...row(), rowVersion: 3, safeForModel: false } });
  });
  renderPanel([row()], changed); fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: reportId } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '合成撤销理由' } });
  fireEvent.click(screen.getByRole('button', { name: '撤销模型许可' }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(body).toEqual({ expectedRowVersion: 2, safeForModel: false, reviewedForPrivacy: false, reviewNote: '合成撤销理由' });
  expect(changed.mock.calls[0][0]).toMatchObject({ status: 'approved', safeForModel: false, rowVersion: 3 });
});

test('privacy HTTP failures remain explicit without calling the parent update', async () => {
  const changed = vi.fn(); vi.stubGlobal('fetch', async () => response({}, 409)); renderPanel([row()], changed);
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: reportId } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '合成理由' } });
  fireEvent.click(screen.getByRole('button', { name: '撤销模型许可' }));
  await screen.findByText(/操作未确认（409）/); expect(changed).not.toHaveBeenCalled();
});

test('missing source context remains an explicit blocker, not an empty verified conversation', async () => {
  const detail = { ...candidateDetail(), availability: 'unavailable', material: null, proofDigest: null, blockers: ['candidate_context_unavailable'] };
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('rule-candidates') ? detail : runs())); renderPanel(); await openCandidate();
  expect(screen.getByText(/原始对话缺失、不完整或过大/)).toBeDefined();
  expect(screen.queryByLabelText('答案有完整事实支持')).toBeNull();
});

test('historical failed regression retains every failed case and unhighlighted fact', async () => {
  const original = candidateDetail();
  const detail = { ...original, availability: 'historical', proofDigest: null, blockers: ['candidate_terminal'],
    candidateStatus: 'published', reviewVersion: 2, publishedRuleVersion: nextRule,
    review: { ...reviewState(), status: 'published', publishedRuleVersion: nextRule }, material: { ...original.material,
      sourceContext: { ...original.material.sourceContext, messages: [] },
      factScope: [...original.material.factScope, { ...original.material.factScope[0], id: 'f1:' + 'e'.repeat(64) }],
      highlightedFactIds: [factId], report: { ...original.material.report, evidenceKind: 'deterministic_regression',
        status: 'failed', passedCaseCount: 0, caseResults: [{ caseId: reportId, suite: 'dev_regression', passed: false, code: 'counterexample' }] } } };
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('rule-candidates') ? detail : runs())); renderPanel(); await openCandidate();
  expect(screen.getByText(/已核验：这次提问之前没有对话/)).toBeDefined();
  expect(screen.getByText(/确定性回归证据，仍需人工核对语义/)).toBeDefined();
  expect(screen.getByText(/counterexample · 未通过/)).toBeDefined();
  expect(screen.getByText(/历史发布版本：/)).toBeDefined(); expect(screen.queryByRole('button', { name: '单独确认发布' })).toBeNull();
});

test('rollback sends a separate bound pointer operation and verifies its acknowledgement', async () => {
  let rolledBack = false; const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body)); posts.push({ url, body }); rolledBack = true;
      return response({ operationKey: body.operationKey, ruleVersion: rule, pointerVersion: 1, markerVersion: null });
    }
    return response(url.includes('rule-candidates') ? { ...candidateDetail(), activeRuleVersion: rolledBack ? rule : nextRule,
      activePointerVersion: rolledBack ? 1 : 0 } : runs());
  });
  renderPanel(); await openCandidate();
  const button = screen.getByRole('button', { name: '确认回滚' }); expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('回滚理由'), { target: { value: '合成规则回滚' } });
  fireEvent.click(screen.getByLabelText('确认目标与当前指针，回滚仅影响新会话')); fireEvent.click(button);
  await waitFor(() => expect(screen.queryByRole('button', { name: '确认回滚' })).toBeNull());
  expect(posts).toHaveLength(1); expect(posts[0].url).toContain('/rule-releases/rollback');
  expect(posts[0].body).toMatchObject({ targetRuleVersion: rule, expectedRuleVersion: nextRule, expectedPointerVersion: 0, reason: '合成规则回滚' });
});

test('a body decoding after token rotation cannot restore a private candidate', async () => {
  let resolve!: (value: unknown) => void;
  vi.stubGlobal('fetch', async (url: string) => url.includes('rule-candidates')
    ? Object.assign(response({}), { json: () => new Promise<unknown>(done => { resolve = done; }) }) : response(runs()));
  const view = renderPanel(); fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看候选' })); await waitFor(() => expect(resolve).toBeTypeOf('function'));
  view.rerender(<AgentReviewPanel token="new-admin" feedbacks={[]} onFeedbackChanged={vi.fn()} />);
  await act(async () => resolve(candidateDetail())); expect(screen.queryByRole('article', { name: '候选审核' })).toBeNull();
});

test('a separately requested task start binds the approved feedback version and reads actual task status', async () => {
  let body: Record<string, unknown> | undefined;
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { body = JSON.parse(String(init.body)); return response({ runId }); }
    return response(agentStatus());
  });
  renderPanel([row()]); fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: reportId } });
  fireEvent.click(screen.getByRole('button', { name: '显式启动修复任务' }));
  await screen.findByText(/原任务状态：awaiting_review · 模型/);
  expect(body).toMatchObject({ feedbackId: reportId, expectedFeedbackVersion: 2 });
  expect(body?.requestId).toMatch(/^[0-9a-f-]{36}$/);
  expect(Object.keys(body!).sort()).toEqual(['expectedFeedbackVersion', 'feedbackId', 'requestId']);
});

test('a genuinely queued task has no candidate instead of a fabricated empty review', async () => {
  const page = runs();
  Object.assign(page.runs[0], { state: 'queued', deadlineAt: null, modelAttemptsUsed: 0,
    toolAttemptsUsed: 0, candidateId: null, candidateStatus: null });
  vi.stubGlobal('fetch', async () => response(page)); renderPanel();
  fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' })); await screen.findByText(/原任务状态：queued · 候选：无/);
  expect(screen.queryByRole('button', { name: '查看候选' })).toBeNull();
});

test('a maximum safe review version cannot produce an unsafe increment or publication request', async () => {
  const detail = { ...candidateDetail(), candidateStatus: 'approved', reviewVersion: Number.MAX_SAFE_INTEGER, review: reviewState() };
  const fetch = vi.fn(async (url: string) => response(url.includes('rule-candidates') ? detail : runs()));
  vi.stubGlobal('fetch', fetch); renderPanel(); await openCandidate();
  fireEvent.click(screen.getByRole('button', { name: '单独确认发布' }));
  expect(fetch).toHaveBeenCalledTimes(2); expect(screen.queryByText(/操作凭证已核验/)).toBeNull();
});

test('a maximum safe pointer version cannot produce an unsafe rollback request', async () => {
  const detail = { ...candidateDetail(), activeRuleVersion: nextRule, activePointerVersion: Number.MAX_SAFE_INTEGER };
  const fetch = vi.fn(async (url: string) => response(url.includes('rule-candidates') ? detail : runs()));
  vi.stubGlobal('fetch', fetch); renderPanel(); await openCandidate();
  fireEvent.change(screen.getByLabelText('回滚理由'), { target: { value: '合成理由' } });
  fireEvent.click(screen.getByLabelText('确认目标与当前指针，回滚仅影响新会话'));
  fireEvent.click(screen.getByRole('button', { name: '确认回滚' })); expect(fetch).toHaveBeenCalledTimes(2);
});

test('privacy permission changes cannot increment a maximum safe feedback version', () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); renderPanel([{ ...row(), rowVersion: Number.MAX_SAFE_INTEGER }]);
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: reportId } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '合成理由' } });
  fireEvent.click(screen.getByRole('button', { name: '撤销模型许可' })); expect(fetch).not.toHaveBeenCalled();
});

test('late privacy acknowledgement cannot update a newly mounted credential session', async () => {
  let finish!: (value: unknown) => void; const changed = vi.fn();
  vi.stubGlobal('fetch', async () => Object.assign(response({}), { json: () => new Promise<unknown>(done => { finish = done; }) }));
  const view = renderPanel([row()], changed);
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: reportId } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '合成理由' } });
  fireEvent.click(screen.getByRole('button', { name: '撤销模型许可' }));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  view.rerender(<AgentReviewPanel token="new-admin" feedbacks={[row()]} onFeedbackChanged={changed} />);
  await act(async () => finish({ ok: true, feedback: { ...row(), rowVersion: 3, safeForModel: false } }));
  expect(changed).not.toHaveBeenCalled();
});

test('a rejected old candidate read stays silent after credential rotation', async () => {
  let reject!: (reason: Error) => void;
  vi.stubGlobal('fetch', (url: string) => url.includes('rule-candidates')
    ? new Promise<Response>((_done, fail) => { reject = fail; }) : Promise.resolve(response(runs())));
  const view = renderPanel(); fireEvent.click(screen.getByRole('button', { name: '刷新任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看候选' })); await waitFor(() => expect(reject).toBeTypeOf('function'));
  view.rerender(<AgentReviewPanel token="new-admin" feedbacks={[]} onFeedbackChanged={vi.fn()} />);
  await act(async () => reject(new Error('OLD_PRIVATE_ERROR'))); expect(screen.queryByRole('alert')).toBeNull();
});
