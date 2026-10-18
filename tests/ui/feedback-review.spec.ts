import { test, expect, API } from './fixtures';
import { randomUUID } from 'node:crypto';

const admin = { 'X-Admin-Token': 'e2e-test-only' };

test('blank answer feedback is rejected over HTTP without poisoning subsequent admin review', async ({ page, request }, info) => {
  const question = `空白反馈隔离 ${randomUUID()}？`;
  const valid = { soupId: 'xin', question, hostAnswer: '不是', expectedAnswer: '是', reason: '' };
  for (const field of ['hostAnswer', 'expectedAnswer'] as const) {
    const rejected = await request.post(`${API}/api/feedback`, { data: { ...valid, [field]: ' \t\u3000 ' } });
    expect(rejected.status()).toBe(422);
  }
  const before = await request.get(`${API}/api/feedback/admin`, { headers: admin });
  expect(before.ok()).toBeTruthy();
  expect((await before.json()).feedbacks.some((item: { question: string }) => item.question === question)).toBe(false);
  const created = await request.post(`${API}/api/feedback`, { data: valid });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { id } = await created.json();
  await page.addInitScript(() => localStorage.setItem('turtle_admin_token', 'e2e-test-only'));
  await page.goto('/admin/feedback');
  const card = page.locator('div.card').filter({ hasText: question });
  await expect(card.getByText('审核版本：0', { exact: true })).toBeVisible();
  const reviewed = page.waitForResponse(r => r.url() === `${API}/api/feedback/admin/${id}/approve`);
  await card.getByRole('button', { name: '通过 ✅', exact: true }).click();
  const response = await reviewed;
  expect(response.ok()).toBeTruthy();
  expect((await response.json()).feedback.safeForModel).toBe(false);
  await expect(card.getByText('审核版本：1', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('blank-feedback-rejected-valid-review.png'), fullPage: true });
});

test('real public feedback reaches versioned admin review but is not model permission or truth', async ({ page, request }, info) => {
  const question = `这是合成反馈审核 ${randomUUID()} 吗？`;
  await page.goto('/');
  await page.getByRole('button', { name: '主持人答错了？点此提交反馈' }).click();
  await page.getByRole('combobox', { name: '选择反馈汤品' }).selectOption('xin');
  await page.getByPlaceholder('例如：故事中只有六个人吗？').fill(question);
  await page.locator('select').filter({ has: page.locator('option[value=""]', { hasText: '请选择主持人的回答…' }) }).selectOption('不是');
  await page.locator('select').filter({ has: page.locator('option[value=""]', { hasText: '请选择标准答案…' }) }).selectOption('是');
  const submitted = page.waitForResponse(r => r.url() === `${API}/api/feedback` && r.request().method() === 'POST');
  await page.getByRole('button', { name: '提交反馈', exact: true }).click();
  const response = await submitted; expect(response.ok()).toBeTruthy();
  const publicBody = await response.json(); expect(Object.keys(publicBody).sort()).toEqual(['id', 'ok']);
  await expect(page.getByText('✅ 提交成功，感谢反馈！', { exact: true })).toBeVisible();
  await page.goto('/admin/feedback'); await page.getByPlaceholder('管理口令').fill('e2e-test-only');
  await page.getByRole('button', { name: '进入', exact: true }).click();
  const card = page.locator('div.card').filter({ hasText: question });
  await expect(card.getByText('审核版本：0', { exact: true })).toBeVisible();
  await expect(card.getByText('玩家认为应答：', { exact: true })).toBeVisible();
  const reviewed = page.waitForResponse(r => r.url() === `${API}/api/feedback/admin/${publicBody.id}/approve`);
  await card.getByRole('button', { name: '通过 ✅', exact: true }).click();
  const review = await reviewed; expect(review.ok()).toBeTruthy();
  expect(review.request().postDataJSON()).toEqual({ expectedRowVersion: 0 });
  const actual = (await review.json()).feedback;
  expect(actual.status).toBe('approved'); expect(actual.rowVersion).toBe(1); expect(actual.safeForModel).toBe(false);
  expect(actual.mergedAt).toBeNull(); expect(actual.mergedAnswer).toBeNull();
  await expect(card.getByText('审核版本：1', { exact: true })).toBeVisible();
  expect((await request.post(`${API}/api/feedback/admin/merge-verified`, { headers: admin })).status()).toBe(410);
  await page.screenshot({ path: info.outputPath('feedback-reviewed-not-truth.png'), fullPage: true });
});

test('another admin review causes real 409 and stale page waits for refreshed server state', async ({ page, request }, info) => {
  const question = `合成审核冲突 ${randomUUID()}？`;
  const created = await request.post(`${API}/api/feedback`, { data: { soupId: 'xin', question, hostAnswer: '不是', expectedAnswer: '是', reason: '' } });
  expect(created.ok(), await created.text()).toBeTruthy(); const { id } = await created.json();
  await page.addInitScript(() => localStorage.setItem('turtle_admin_token', 'e2e-test-only'));
  await page.goto('/admin/feedback'); const card = page.locator('div.card').filter({ hasText: question });
  await expect(card.getByText('审核版本：0', { exact: true })).toBeVisible();
  const other = await request.post(`${API}/api/feedback/admin/${id}/reject`, { headers: admin, data: { expectedRowVersion: 0 } });
  expect(other.ok()).toBeTruthy();
  const conflict = page.waitForResponse(r => r.url() === `${API}/api/feedback/admin/${id}/approve`);
  await card.getByRole('button', { name: '通过 ✅', exact: true }).click();
  expect((await conflict).status()).toBe(409);
  await expect(page.getByText('这条反馈已被其他审核更新，请刷新后重新核对', { exact: true })).toBeVisible();
  await expect(card.getByText('审核版本：0', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(card.getByText('审核版本：1', { exact: true })).toBeVisible();
  await expect(card.getByRole('button', { name: '通过 ✅', exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('feedback-cas-conflict.png'), fullPage: true });
});

test('owned rule pause preserves pending UUID and original game until explicit resume and sync', async ({ page, request }, info) => {
  let asks = 0; let creates = 0; let operation = '';
  await page.route(`${API}/api/chat`, async route => {
    const body = route.request().postDataJSON();
    if (!body.question) { creates++; await route.continue(); return; }
    asks++;
    if (asks === 1) { operation = body.requestId; await route.abort('failed'); return; }
    expect(body.requestId).toBe(operation); await route.continue();
  });
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  const original = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  await input.fill('这是合成停版恢复的问题吗？'); await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Failed to fetch' })).toBeVisible();
  const mark = async (suspended: boolean) => {
    const result = await request.post(`${API}/testing/rule-suspension`, {
      headers: { 'X-Test-Instance-Id': process.env.TURTLE_SOUP_TEST_INSTANCE_ID! }, data: { sessionId: original.sessionId, suspended },
    }); expect(result.ok()).toBeTruthy();
  };
  await mark(true);
  try {
    await page.reload(); await expect(page.getByRole('button', { name: '检查暂停是否解除', exact: true })).toBeVisible();
    await expect(input).toBeDisabled(); await expect(page.getByRole('button', { name: '揭晓答案', exact: true })).toBeDisabled();
    expect(asks).toBe(1); expect(creates).toBe(1);
    const pending = await page.evaluate(() => JSON.parse(localStorage.getItem('game_operation_v1:["xin","xuermu"]')!));
    expect(pending.operation.requestId).toBe(operation);
    const paused = await (await request.get(`${API}/api/session/${original.sessionId}`)).json();
    expect(paused.ruleSuspended).toBe(true); expect(paused.questionsAsked).toBe(0); expect(paused.messages).toEqual([]);
    await page.screenshot({ path: info.outputPath('paused-original-request.png'), fullPage: true });
    await mark(false); await page.getByRole('button', { name: '检查暂停是否解除', exact: true }).click();
    await expect(input).toBeEnabled(); expect(asks).toBe(2); expect(creates).toBe(1);
    const resumed = await (await request.get(`${API}/api/session/${original.sessionId}`)).json();
    expect(resumed.questionsAsked).toBe(1); expect(resumed.messages.filter((m: { role: string }) => m.role === 'user')).toHaveLength(1);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!).sessionId)).toBe(original.sessionId);
    expect(await page.evaluate(() => localStorage.getItem('game_operation_v1:["xin","xuermu"]'))).toBeNull();
  } finally { await mark(false); }
});
