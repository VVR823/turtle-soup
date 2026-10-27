import { test, expect, API } from './fixtures';
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import type { Page, APIRequestContext } from '@playwright/test';

const admin = { 'X-Admin-Token': 'e2e-test-only' }, question = '小明是凶手吗？', precedingQuestion = '小红是凶手吗？';
async function linkedFeedback(page: Page) {
  const marker = `Declared synthetic UI feedback ${randomUUID()}`;
  await page.goto('/game/synthetic-ui?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  const old = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  await input.fill(precedingQuestion);
  const previous = page.waitForResponse(response => response.url() === `${API}/api/chat`
    && response.request().postDataJSON().question === precedingQuestion);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const actualPrevious = await (await previous).json();
  expect(actualPrevious.state).toBe('completed'); expect(actualPrevious.reply).toBe('与此无关');
  await input.fill(question);
  const asked = page.waitForResponse(response => response.url() === `${API}/api/chat` && response.request().postDataJSON().question === question);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const actual = await (await asked).json(); expect(actual.state).toBe('completed'); expect(actual.reply).toBe('不是');
  const perTurnFeedback = page.getByRole('button', { name: '反馈这次回答', exact: true });
  await expect(perTurnFeedback).toHaveCount(2); // Response arrived before React committed the new turn.
  await perTurnFeedback.last().click();
  await expect(page.getByRole('combobox', { name: '选择反馈汤品' })).toBeDisabled();
  await expect(page.getByPlaceholder('例如：故事中只有六个人吗？')).toHaveValue(question);
  await page.locator('select').filter({ has: page.locator('option[value=""]', { hasText: '请选择标准答案…' }) }).selectOption('是');
  await page.getByPlaceholder('可补充为什么你认为主持人答错了').fill(marker);
  const submitted = page.waitForResponse(response => response.url() === `${API}/api/feedback` && response.request().method() === 'POST');
  await page.getByRole('button', { name: '提交反馈', exact: true }).click();
  const reply = await submitted; expect(reply.ok()).toBeTruthy(); expect(reply.request().postDataJSON().turnId).toBe(actual.turnId);
  const fid = (await reply.json()).id;
  await page.addInitScript(() => localStorage.setItem('turtle_admin_token', 'e2e-test-only'));
  await page.goto('/admin/feedback');
  const card = page.locator('div.card').filter({ hasText: marker });
  await expect(card.getByText('审核版本：0', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: '确认反馈有效', exact: true }).click();
  await expect(card.getByText('审核版本：1', { exact: true })).toBeVisible();
  return { fid, oldSession: old.sessionId as string };
}
async function candidateFromBrowser(page: Page, request: APIRequestContext, fid: string) {
  await page.getByRole('button', { name: '高级：AI 修正规则' }).click();
  const panel = page.getByRole('region', { name: '任务与候选管理' });
  await panel.getByLabel('选择反馈').selectOption(fid);
  await expect(panel.getByRole('button', { name: '显式启动修复任务' })).toBeDisabled();
  await panel.getByLabel('隐私审核理由').fill('Declared synthetic manual privacy review, not human quality');
  await panel.getByLabel('脱敏后的反馈背景').fill('');
  await expect(panel.getByLabel('已逐项检查隐私与脱敏内容')).not.toBeChecked();
  await panel.getByLabel('已逐项检查隐私与脱敏内容').check();
  const privacy = page.waitForResponse(response => response.url() === `${API}/api/feedback/admin/${fid}/privacy`);
  await panel.getByRole('button', { name: '保存脱敏授权（不启动任务）' }).click();
  const saved = await privacy; expect(saved.ok(), await saved.text()).toBeTruthy();
  expect(saved.request().postDataJSON()).toMatchObject({ expectedRowVersion: 1, reviewedForPrivacy: true, safeForModel: true });
  await expect(panel.getByRole('button', { name: '显式启动修复任务' })).toBeEnabled();
  await expect(panel.getByLabel('已逐项检查隐私与脱敏内容')).not.toBeChecked();
  await expect(panel.getByLabel('脱敏后的反馈背景')).toHaveValue('');
  await expect(panel.getByLabel('隐私审核理由')).toHaveValue('');
  const started = page.waitForResponse(response => response.url() === `${API}/api/feedback/admin/agent-runs` && response.request().method() === 'POST');
  await panel.getByRole('button', { name: '显式启动修复任务' }).click();
  const admitted = await started; expect(admitted.status()).toBe(202);
  const run = (await admitted.json()).runId;
  expect(admitted.request().postDataJSON().expectedFeedbackVersion).toBe(2);
  await expect.poll(async () => (await (await request.get(`${API}/api/feedback/admin/agent-runs/${run}`, { headers: admin })).json()).state,
    // Real tool subprocess startup can exceed 10s on Windows. This only
    // bounds test observation; model/tool limits and business deadlines stay intact.
    { timeout: 30000, intervals: [250, 500, 1000] }).toBe('awaiting_review');
  const actual = await (await request.get(`${API}/api/feedback/admin/agent-runs/${run}`, { headers: admin })).json();
  expect(actual.modelAttemptsUsed).toBe(3); expect(actual.toolAttemptsUsed).toBe(2);
  await panel.getByRole('button', { name: '刷新任务列表' }).click();
  await panel.locator('article').filter({ hasText: run }).getByRole('button', { name: '查看候选', exact: true }).click();
  const detail = panel.getByRole('article', { name: '候选审核' });
  await expect(detail.getByText('完整事实与限定条件（不得仅凭模型摘要批准）', { exact: true })).toBeVisible();
  await expect(detail.getByRole('heading', { name: '原始提问与之前对话（仅人工核对）' })).toBeVisible();
  await expect(detail.getByText(precedingQuestion, { exact: true })).toBeVisible();
  await expect(detail.getByText('小明是凶手。', { exact: false })).toBeVisible();
  await expect(detail.getByText('合成测试证据，不是真实模型/真人人审成绩', { exact: true })).toBeVisible();
  await expect(detail.getByLabel('答案有完整事实支持')).not.toBeChecked();
  await expect(detail.getByLabel('不依赖玩家当前上下文')).not.toBeChecked();
  await expect(detail.getByRole('button', { name: '批准候选（不发布）' })).toBeDisabled();
  return { panel, detail, run, cid: actual.candidateId as string };
}

test('missing current trusted corpus refuses loaded browser approval and shows only minimal unavailable state', async ({ page, request }, info) => {
  test.setTimeout(45000);
  const errors: string[] = [], consoleErrors: string[] = [], outside: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('request', req => {
    const url = new URL(req.url());
    if ((url.protocol === 'http:' || url.protocol === 'https:')
      && !['http://127.0.0.1:18080', 'http://127.0.0.1:18081'].includes(url.origin)) outside.push(url.origin);
  });
  const { fid, oldSession } = await linkedFeedback(page);
  const { panel, detail, cid } = await candidateFromBrowser(page, request, fid);
  const endpoint = `${API}/api/feedback/admin/rule-candidates/${cid}`;
  const before = await (await request.get(endpoint, { headers: admin })).json();
  const session = await (await request.get(`${API}/api/session/${oldSession}`)).json();
  const owned = { 'X-Test-Instance-Id': process.env.TURTLE_SOUP_TEST_INSTANCE_ID! };
  await detail.getByLabel('候选审核理由').fill('Declared synthetic missing corpus refusal, not human quality');
  await detail.getByLabel('答案有完整事实支持').check();
  await detail.getByLabel('不依赖玩家当前上下文').check();
  await expect(detail.getByRole('button', { name: '批准候选（不发布）' })).toBeEnabled();
  await page.screenshot({ path: info.outputPath('trusted-corpus-loaded-pending.png'), fullPage: true });
  try {
    const withdrawal = await request.post(`${API}/testing/corpus-availability`, { headers: owned, data: { available: false } });
    expect(withdrawal.status()).toBe(200); expect(await withdrawal.json()).toEqual({ available: false });
    const refused = page.waitForResponse(response => response.url() === `${endpoint}/approve` && response.request().method() === 'POST');
    await detail.getByRole('button', { name: '批准候选（不发布）' }).click();
    const rejection = await refused; expect(rejection.status()).toBe(409);
    expect(rejection.request().postDataJSON()).toMatchObject({ answerSupported: true, contextIndependent: true,
      expectedProofDigest: before.proofDigest, expectedReviewVersion: 0 });
    await expect(panel.getByRole('alert')).toBeVisible();
    await page.screenshot({ path: info.outputPath('missing-corpus-approval-refused.png'), fullPage: true });
    await panel.getByRole('button', { name: '刷新候选实际状态' }).click();
    await expect(detail.getByText(/candidate_corpus_missing/)).toBeVisible();
    await expect(detail.getByText(/材料：unavailable/)).toBeVisible();
    await expect(detail.getByText('完整事实与限定条件（不得仅凭模型摘要批准）', { exact: true })).toHaveCount(0);
    await expect(detail.getByRole('button', { name: '批准候选（不发布）' })).toHaveCount(0);
    await expect(detail.getByRole('button', { name: '单独确认发布' })).toHaveCount(0);
    const actual = await (await request.get(endpoint, { headers: admin })).json();
    expect(actual).toMatchObject({ availability: 'unavailable', material: null, proofDigest: null,
      blockers: ['candidate_corpus_missing'], candidateStatus: 'pending', reviewVersion: 0, review: null,
      publishedRuleVersion: null, activeRuleVersion: before.activeRuleVersion, activePointerVersion: before.activePointerVersion });
    expect(await (await request.get(`${API}/api/session/${oldSession}`)).json()).toEqual(session);
    await page.screenshot({ path: info.outputPath('missing-corpus-minimal-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(detail.getByText(/candidate_corpus_missing/)).toBeVisible();
    const layout = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, width: document.documentElement.scrollWidth }));
    expect(layout.viewport).toBe(375); expect(layout.width).toBeLessThanOrEqual(376);
    await page.screenshot({ path: info.outputPath('missing-corpus-minimal-mobile.png'), fullPage: true });
    expect(errors).toEqual([]); expect(outside).toEqual([]);
    expect(consoleErrors.every(message => message.includes('409'))).toBe(true);
    const observationPath = info.outputPath('missing-corpus-observation.json');
    await writeFile(observationPath, JSON.stringify({ status: rejection.status(),
      availability: actual.availability, state: actual.candidateStatus, reviewVersion: actual.reviewVersion,
      uncaught: errors, consoleErrors, outside, layout }) + '\n', { flag: 'wx' });
    await info.attach('missing-corpus-observation', { path: observationPath, contentType: 'application/json' });
  } finally {
    const restored = await request.post(`${API}/testing/corpus-availability`, { headers: owned, data: { available: true } });
    expect(restored.status()).toBe(200); expect(await restored.json()).toEqual({ available: true });
    const ready = await (await request.get(endpoint, { headers: admin })).json();
    expect(ready.availability).toBe('ready'); expect(ready.proofDigest).toBe(before.proofDigest);
  }
});

test('genuine browser feedback/privacy/worker/manual approval exact replay/publication/new sessions/rollback retains history', async ({ page, request }, info) => {
  // Includes a cold real worker plus several proof-bound mutations and reads.
  test.setTimeout(90000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const { fid, oldSession } = await linkedFeedback(page);
  const { panel, detail, run, cid } = await candidateFromBrowser(page, request, fid);
  const pinned = await (await request.get(`${API}/api/feedback/admin/rule-candidates/${cid}`, { headers: admin })).json();
  expect(pinned.material.report.inputCaseCount).toBe(7); expect(pinned.material.report.caseResults).toHaveLength(7);
  expect(pinned.material.sourceContext).toMatchObject({ scope: 'admin_review_only', originalQuestion: question,
    originalHostAnswer: '不是', messages: [{ role: 'user', content: precedingQuestion }, { role: 'host', content: '与此无关' }] });
  const base = pinned.activeRuleVersion;
  await page.screenshot({ path: info.outputPath('candidate-unchecked-complete-evidence.png'), fullPage: true });
  const bodies: unknown[] = [];
  await page.route(`${API}/api/feedback/admin/rule-candidates/${cid}/approve`, async route => {
    bodies.push(route.request().postDataJSON());
    const committed = await route.fetch({ maxRedirects: 0 }); expect(committed.ok()).toBeTruthy();
    if (bodies.length === 1) await route.abort('failed'); else await route.fulfill({ response: committed });
  });
  await detail.getByLabel('候选审核理由').fill('Declared synthetic semantic confirmations for UI mechanics only');
  await detail.getByLabel('答案有完整事实支持').check(); await detail.getByLabel('不依赖玩家当前上下文').check();
  // Observe the deliberately lost reply after the real commit has finished.
  // Proof verification alone can approach the default 5s assertion timeout.
  const dropped = page.waitForEvent('requestfailed', {
    predicate: request => request.url() === `${API}/api/feedback/admin/rule-candidates/${cid}/approve`, timeout: 30000,
  });
  await detail.getByRole('button', { name: '批准候选（不发布）' }).click();
  await dropped;
  await expect(panel.getByRole('alert').filter({ hasText: '可能已经提交' })).toBeVisible();
  expect(bodies).toHaveLength(1); expect((await (await request.get(`${API}/api/feedback/admin/rule-candidates/${cid}`, { headers: admin })).json()).candidateStatus).toBe('approved');
  await page.screenshot({ path: info.outputPath('approval-committed-reply-lost.png'), fullPage: true });
  await panel.getByRole('button', { name: '重试原操作（相同请求）' }).click();
  await expect(detail.getByRole('button', { name: '单独确认发布' })).toBeVisible();
  expect(bodies).toHaveLength(2); expect(bodies[1]).toEqual(bodies[0]);
  const approved = await (await request.get(`${API}/api/feedback/admin/rule-candidates/${cid}`, { headers: admin })).json();
  expect(approved.activeRuleVersion).toBe(base); expect(approved.reviewVersion).toBe(1);
  const published = page.waitForResponse(response => response.url() === `${API}/api/feedback/admin/rule-candidates/${cid}/publish`);
  await detail.getByRole('button', { name: '单独确认发布' }).click();
  const publication = await published; expect(publication.ok(), await publication.text()).toBeTruthy();
  const release = (await publication.json()).publishedRuleVersion; expect(release).not.toBe(base);
  await expect(detail.getByText(/候选工作流：published/)).toBeVisible();
  const newSession = (await (await request.post(`${API}/api/chat`, { data: { soupId: 'synthetic-ui', requestId: randomUUID() } })).json()).sessionId;
  const ask = async (sessionId: string) => (await (await request.post(`${API}/api/chat`, {
    data: { sessionId, question, requestId: randomUUID() } })).json()).reply;
  expect(await ask(newSession)).toBe('是'); expect(await ask(oldSession)).toBe('不是');
  const preserved = await (await request.get(`${API}/api/session/${oldSession}`)).json();
  expect(preserved.ruleVersion).toBe(base); expect(preserved.questionsAsked).toBe(3);
  await detail.getByLabel('回滚理由').fill('Declared synthetic restore to loaded original base');
  await detail.getByLabel('确认目标与当前指针，回滚仅影响新会话').check();
  const rolled = page.waitForResponse(response => response.url() === `${API}/api/feedback/admin/rule-releases/rollback`);
  await detail.getByRole('button', { name: '确认回滚' }).click();
  const restored = await rolled; expect(restored.ok(), await restored.text()).toBeTruthy(); expect((await restored.json()).ruleVersion).toBe(base);
  const restoredSession = (await (await request.post(`${API}/api/chat`, { data: { soupId: 'synthetic-ui', requestId: randomUUID() } })).json()).sessionId;
  expect(await ask(restoredSession)).toBe('不是'); expect(await ask(newSession)).toBe('是');
  await expect(detail.getByText(/候选工作流：published/)).toBeVisible();
  const history = await (await request.get(`${API}/api/feedback/admin/rule-candidates/${cid}`, { headers: admin })).json();
  expect(history.activeRuleVersion).toBe(base); expect(history.publishedRuleVersion).toBe(release);
  expect(history.agentStatus.state).toBe('awaiting_review'); expect(history.material.report.caseResults).toHaveLength(7);
  expect(history.material.sourceContext).toEqual(pinned.material.sourceContext);
  expect((await (await request.get(`${API}/api/feedback/admin/agent-runs/${run}`, { headers: admin })).json()).state).toBe('awaiting_review');
  await page.screenshot({ path: info.outputPath('rollback-retains-published-candidate-and-original-task.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('actual privacy withdrawal produces minimal stale candidate that can be rejected but never published', async ({ page, request }, info) => {
  test.setTimeout(45000);
  const { fid } = await linkedFeedback(page);
  const { panel, detail, cid } = await candidateFromBrowser(page, request, fid);
  await panel.getByLabel('隐私审核理由').fill('Declared synthetic privacy withdrawal');
  const withdrawn = page.waitForResponse(response => response.url() === `${API}/api/feedback/admin/${fid}/privacy`);
  await panel.getByRole('button', { name: '撤销模型许可' }).click(); expect((await withdrawn).ok()).toBeTruthy();
  await panel.getByRole('button', { name: '刷新候选实际状态' }).click();
  await expect(detail.getByText(/candidate_source_stale/)).toBeVisible();
  await expect(detail.getByText('完整事实与限定条件（不得仅凭模型摘要批准）', { exact: true })).toHaveCount(0);
  await expect(detail.getByRole('button', { name: '批准候选（不发布）' })).toHaveCount(0);
  await detail.getByLabel('候选审核理由').fill('Declined synthetic stale proposal');
  const rejected = page.waitForResponse(response => response.url() === `${API}/api/feedback/admin/rule-candidates/${cid}/reject`);
  await detail.getByRole('button', { name: '拒绝候选' }).click(); expect((await rejected).ok()).toBeTruthy();
  await expect(detail.getByText(/候选工作流：rejected/)).toBeVisible();
  await expect(detail.getByRole('button', { name: '单独确认发布' })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('withdrawn-material-minimal-and-rejected.png'), fullPage: true });
});
