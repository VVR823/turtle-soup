import { test, expect, API } from './fixtures';
import { candidateDetail, candidateId, reportId, runId } from '../frontend/agent-review-fixtures';

const feedback = { id: reportId, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: '合成后台恢复测试',
  question: '他知道吗？', hostAnswer: '不是', expectedAnswer: '是', reason: null, status: 'approved',
  reviewedAt: '2026-10-09T00:00:01Z', mergedAt: null, mergedAnswer: null, rowVersion: 2,
  safeForModel: true, sourceState: 'linked', turnId: runId };
const list = { feedbacks: [feedback], totalInRange: 2, nextCursor: 'synthetic-next' };

test('HTTP-compatible admin mutations keep secure UUIDs without browser randomUUID', async ({ page }) => {
  const errors: string[] = [], bodies: Record<string, unknown>[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem('turtle_admin_token', 'synthetic-admin');
    Object.defineProperty(Crypto.prototype, 'randomUUID', { configurable: true, value: undefined });
  });
  await page.route(`${API}/api/feedback/admin**`, async route => {
    const req = route.request(), url = new URL(req.url());
    if (req.method() === 'POST') { bodies.push(req.postDataJSON()); return route.fulfill({ status: 503, json: {} }); }
    if (url.pathname.endsWith('/agent-runs')) return route.fulfill({ json: { schemaVersion: 1, nextCursor: null,
      runs: [{ id: runId, feedbackId: reportId, state: 'awaiting_review', rowVersion: 9, createdAt: 0,
        deadlineAt: 180, modelAttemptsUsed: 3, toolAttemptsUsed: 2, candidateId, candidateStatus: 'pending' }] } });
    return route.fulfill({ json: url.pathname.includes('/rule-candidates/') ? candidateDetail() : list });
  });
  await page.goto('/admin/feedback');
  await page.getByRole('button', { name: '高级：AI 修正规则' }).click();
  await page.getByRole('button', { name: '刷新任务列表' }).click();
  await page.getByRole('button', { name: '查看候选', exact: true }).click();
  await page.getByLabel('候选审核理由').fill('合成材料，事实不充分');
  await page.getByRole('button', { name: '拒绝候选', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '此功能暂不可用' })).toBeVisible();
  expect(bodies).toHaveLength(1); expect(bodies[0].operationKey).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(errors).toEqual([]);
});

test('a stalled feedback request releases refresh and the next explicit fetch succeeds', async ({ page }) => {
  let reads = 0;
  await page.clock.install();
  await page.addInitScript(() => localStorage.setItem('turtle_admin_token', 'synthetic-admin'));
  await page.route(`${API}/api/feedback/admin`, async route => { if (++reads === 1) return; await route.fulfill({ json: list }); });
  await page.goto('/admin/feedback');
  await expect(page.getByRole('button', { name: '刷新中…' })).toBeDisabled();
  await expect.poll(() => reads).toBe(1);
  await page.clock.fastForward(31000);
  await expect(page.getByText('反馈加载超时，请点击刷新重试')).toBeVisible();
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByText('他知道吗？', { exact: true })).toBeVisible();
  expect(reads).toBe(2);
});

test('blocked storage gives a usable login explanation with no private request', async ({ page }) => {
  const errors: string[] = [], requests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().includes('/api/feedback/admin')) requests.push(request.url()); });
  await page.addInitScript(() => { Object.defineProperty(Storage.prototype, 'setItem', {
    value() { throw new DOMException('Synthetic storage blocked', 'QuotaExceededError'); },
  }); });
  await page.goto('/admin/feedback');
  await page.getByPlaceholder('管理口令').fill('synthetic-admin');
  await page.getByRole('button', { name: '进入', exact: true }).click();
  await expect(page.getByText(/无法保存管理口令/)).toBeVisible();
  expect(errors).toEqual([]); expect(requests).toEqual([]);
});

test('mobile admin labels loaded pending counts and keeps technical filters hidden', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.addInitScript(() => localStorage.setItem('turtle_admin_token', 'synthetic-admin'));
  await page.route(`${API}/api/feedback/admin`, route => route.fulfill({ json: list }));
  await page.goto('/admin/feedback');
  await expect(page.getByText('已加载中 0 条待处理', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '加载更多' })).toBeVisible();
  await page.getByText('高级：查看运行数据（平时不用）', { exact: true }).click();
  await expect(page.getByLabel('题目ID')).toBeHidden();
  await expect(page.getByRole('button', { name: '查询统计', exact: true })).toBeVisible();
  await page.getByText('高级筛选（通常不用填写）', { exact: true }).click();
  await expect(page.getByLabel('题目ID')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
