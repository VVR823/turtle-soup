import { test, expect, API } from './fixtures';

test('creation missing its count stays disabled and manual sync replays its original identity', async ({ page, request }) => {
  const identities: string[] = []; let sessionId = '';
  const malformed = async (route: import('@playwright/test').Route) => {
    const body = route.request().postDataJSON(); identities.push(body.requestId);
    const response = await route.fetch({ maxRedirects: 0 }); expect(response.ok()).toBeTruthy();
    const result = await response.json(); sessionId = result.sessionId; delete result.questionLimit;
    await route.fulfill({ response, json: result });
  };
  await page.route(`${API}/api/chat`, malformed); await page.goto('/game/xin?level=xuermu');
  await expect(page.getByRole('alert').filter({ hasText: '无法核验' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '揭晓答案', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => localStorage.getItem('last_session'))).toBeNull();
  const pending = await page.evaluate(() => JSON.parse(localStorage.getItem('game_operation_v1:["xin","xuermu"]')!));
  expect(pending.operation.requestId).toBe(identities[0]);
  await page.unroute(`${API}/api/chat`, malformed);
  await page.route(`${API}/api/chat`, async route => { identities.push(route.request().postDataJSON().requestId); await route.continue(); });
  await page.getByRole('button', { name: '同步原对局' }).click();
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeEnabled();
  expect(identities).toHaveLength(2); expect(identities[1]).toBe(identities[0]);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!).sessionId)).toBe(sessionId);
  const state = await (await request.get(`${API}/api/session/${sessionId}`)).json(); expect(state.questionsAsked).toBe(0);
});

test('initialization disables actions; the durable creation UUID precedes one POST', async ({ page }) => {
  let release!: () => void; const hold = new Promise<void>(resolve => { release = resolve; });
  let payload: Record<string, unknown> | null = null; let posts = 0;
  await page.route(`${API}/api/chat`, async route => {
    payload = route.request().postDataJSON(); posts++;
    await hold; await route.continue();
  });
  await page.goto('/game/xin?level=xuermu');
  await expect.poll(() => posts).toBe(1);
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '揭晓答案', exact: true })).toBeDisabled();
  const journal = await page.evaluate(() => JSON.parse(localStorage.getItem('game_operation_v1:["xin","xuermu"]')!));
  expect(journal.operation.requestId).toBe(payload!.requestId);
  expect(journal.operation.kind).toBe('create'); release();
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeEnabled();
  const saved = await page.evaluate(() => localStorage.getItem('last_session'));
  await page.reload();
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeEnabled();
  expect(posts).toBe(1); expect(await page.evaluate(() => localStorage.getItem('last_session'))).toBe(saved);
});

test('same-tick submit creates one question; playing responses never expose answers or HostResult', async ({ page, request }) => {
  let asks = 0;
  await page.route(`${API}/api/chat`, async route => {
    if (route.request().postDataJSON().question) asks++;
    await route.continue();
  });
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' });
  await expect(input).toBeEnabled(); await input.fill('这封信是在测试恢复吗？');
  await page.getByRole('button', { name: '发送', exact: true }).evaluate(button => {
    (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click();
  });
  await expect(input).toBeEnabled(); expect(asks).toBe(1);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  const response = await request.get(`${API}/api/session/${saved.sessionId}`);
  const state = await response.json(); expect(state.questionsAsked).toBe(1); expect(state.status).toBe('playing');
  expect(state.evaluation).toBeNull();
  expect(JSON.stringify(state)).not.toMatch(/"(?:bottom|hostResult|host_result|evidence|confirmed_fact_ids|scoreEvidence)"/);
  await expect(page.getByText('完整汤底', { exact: true })).toHaveCount(0);
});

test('late creation after client level navigation cannot overwrite the next game pointer', async ({ page }) => {
  let release!: () => void; const hold = new Promise<void>(resolve => { release = resolve; });
  let held = false; let settled = false;
  await page.route(`${API}/api/chat`, async route => {
    const old = route.request().postDataJSON().level === 'xuermu';
    if (old) { held = true; await hold; }
    await route.continue().catch(() => {});
    if (old) settled = true;
  });
  await page.goto('/game/xin?level=xuermu'); await expect.poll(() => held).toBe(true);
  await page.getByRole('button', { name: '选择难度', exact: true }).click();
  await expect(page).toHaveURL(/difficulty\/xin/);
  await page.getByRole('button', { name: /包子/ }).click();
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeEnabled();
  const saved = await page.evaluate(() => localStorage.getItem('last_session')); release();
  await expect.poll(() => settled).toBe(true);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!).level)).toBe('baozi');
  expect(await page.evaluate(() => localStorage.getItem('last_session'))).toBe(saved);
});

test('mobile controls are not covered by feedback and do not overflow the viewport', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  await input.evaluate(element => (element as HTMLInputElement).blur());
  await expect(page.getByRole('button', { name: '主持人答错了？点此提交反馈' })).toHaveCSS('opacity', '1');
  await page.screenshot({ path: info.outputPath('mobile-controls.png'), fullPage: true });
  const feedback = await page.getByRole('button', { name: '主持人答错了？点此提交反馈' }).boundingBox();
  const box = await input.boundingBox(); expect(box).not.toBeNull(); expect(feedback).not.toBeNull();
  const overlaps = box!.x < feedback!.x + feedback!.width && box!.x + box!.width > feedback!.x
    && box!.y < feedback!.y + feedback!.height && box!.y + box!.height > feedback!.y;
  expect(overlaps, 'Feedback must not cover any part of the question input').toBe(false);
  expect(await input.evaluate(element => {
    const r = element.getBoundingClientRect(); const top = document.elementFromPoint(r.x + 8, r.y + r.height / 2);
    return top === element;
  })).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('desktop feedback also leaves the sidebar reveal control unobstructed', async ({ page }, info) => {
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  await input.evaluate(element => (element as HTMLInputElement).blur());
  const reveal = page.getByRole('button', { name: '揭晓答案', exact: true }); await reveal.scrollIntoViewIfNeeded();
  const feedbackButton = page.getByRole('button', { name: '主持人答错了？点此提交反馈' }); await expect(feedbackButton).toHaveCSS('opacity', '1');
  await page.screenshot({ path: info.outputPath('desktop-controls.png'), fullPage: true });
  const a = await reveal.boundingBox(); const b = await feedbackButton.boundingBox(); expect(a).not.toBeNull(); expect(b).not.toBeNull();
  expect(a!.x < b!.x + b!.width && a!.x + a!.width > b!.x && a!.y < b!.y + b!.height && a!.y + a!.height > b!.y,
    'Feedback must not cover part of the reveal button').toBe(false);
});
