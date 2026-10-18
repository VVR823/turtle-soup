import { test, expect, API } from './fixtures';
import { randomUUID } from 'node:crypto';

test('A to B to A navigation recovers the committed original request without another charge', async ({ page, request }, info) => {
  let asks = 0; let requestId = ''; const queried: string[] = [];
  await page.route(`${API}/api/session/*/turns/*`, async route => { queried.push(route.request().url().split('/').pop()!); await route.continue(); });
  await page.route(`${API}/api/chat`, async route => {
    const body = route.request().postDataJSON();
    if (!body.question) { await route.continue(); return; }
    asks++; requestId = body.requestId; expect((await route.fetch({ maxRedirects: 0 })).ok()).toBeTruthy(); await route.abort('failed');
  });
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  const original = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  await input.fill('这是切关卡后还需要找回的问题吗？'); await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Failed to fetch' })).toBeVisible();
  await page.goto('/game/xinshijie?level=xuermu'); await expect(input).toBeEnabled();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!).sessionId)).not.toBe(original.sessionId);
  await page.goto('/game/xin?level=xuermu'); await expect(input).toBeEnabled();
  expect(queried).toContain(requestId); expect(asks).toBe(1);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!).sessionId)).toBe(original.sessionId);
  expect(await page.evaluate(() => localStorage.getItem('game_operation_v1:["xin","xuermu"]'))).toBeNull();
  const state = await (await request.get(`${API}/api/session/${original.sessionId}`)).json();
  expect(state.questionsAsked).toBe(1); expect(state.messages.filter((m: { role: string }) => m.role === 'user')).toHaveLength(1);
  await page.screenshot({ path: info.outputPath('navigation-recovered.png'), fullPage: true });
});

test('missing unsubmitted turn restores a result revealed elsewhere without repost or uncharged claim', async ({ page, request }, info) => {
  let asks = 0; let browserReveals = 0;
  await page.route(`${API}/api/chat`, async route => {
    if (!route.request().postDataJSON().question) { await route.continue(); return; }
    asks++; await route.abort('failed'); // never reached the server
  });
  await page.route(`${API}/api/evaluate`, async route => { browserReveals++; await route.continue(); });
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  const original = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  await input.fill('这是尚未提交的原问题吗？'); await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Failed to fetch' })).toBeVisible();
  const ended = await request.post(`${API}/api/evaluate`, { data: { sessionId: original.sessionId } }); expect(ended.ok()).toBeTruthy();
  const snapshot = await (await request.get(`${API}/api/session/${original.sessionId}`)).json();
  await page.reload(); await expect(page.getByText('完整汤底', { exact: true })).toBeVisible();
  expect(asks).toBe(1); expect(browserReveals).toBe(0);
  await expect(page.getByRole('alert').filter({ hasText: /没有扣次数|未扣次数/ })).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('game_operation_v1:["xin","xuermu"]'))).toBeNull();
  const final = await (await request.get(`${API}/api/session/${original.sessionId}`)).json();
  expect(final.status).toBe('given_up'); expect(final.questionsAsked).toBe(0); expect(final.evaluation).toEqual(snapshot.evaluation);
  await page.screenshot({ path: info.outputPath('missing-turn-ended.png'), fullPage: true });
});

test('real exhausted fixture automatically reveals once and keeps its final count', async ({ page, request }, info) => {
  const created = await request.post(`${API}/api/chat`, { data: { soupId: 'xin', level: 'xuermu', requestId: randomUUID() } });
  expect(created.ok()).toBeTruthy(); const game = await created.json(); expect(game.questionLimit).toBe(35);
  for (let index = 0; index < game.questionLimit; index++) {
    const turn = await request.post(`${API}/api/chat`, { data: { sessionId: game.sessionId, requestId: randomUUID(), question: `这是工程合成恢复验证第${index}次吗？` } });
    expect(turn.ok()).toBeTruthy(); expect((await turn.json()).kind).toBe('answer');
  }
  let reveals = 0; let creates = 0;
  await page.addInitScript(game => localStorage.setItem('last_session', JSON.stringify({ sessionId: game.sessionId, soupId: 'xin', level: 'xuermu' })), game);
  await page.route(`${API}/api/chat`, async route => { creates++; await route.continue(); });
  await page.route(`${API}/api/evaluate`, async route => { reveals++; await route.continue(); });
  await page.goto('/game/xin?level=xuermu'); await expect(page.getByText('完整汤底', { exact: true })).toBeVisible();
  const ended = await (await request.get(`${API}/api/session/${game.sessionId}`)).json();
  expect(ended.status).toBe('given_up'); expect(ended.questionsAsked).toBe(35); expect(ended.remaining).toBe(0);
  expect(reveals).toBe(1); expect(creates).toBe(0);
  await page.reload(); await expect(page.getByText('完整汤底', { exact: true })).toBeVisible(); expect(reveals).toBe(1);
  await page.screenshot({ path: info.outputPath('zero-budget-ended.png'), fullPage: true });
});

test('real deterministic win automatically evaluates but plot100 is not a reconstruction score', async ({ page, request }, info) => {
  await page.goto('/game/xinshijie?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  const pointer = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  await input.fill('我是不是还在织梦者的那个梦里'); await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByText('完整汤底', { exact: true })).toBeVisible();
  await expect(page.getByText('剧情进度（非还原评分）：100%', { exact: true })).toBeVisible();
  await expect(page.getByText('还原程度：尚未独立评估', { exact: true })).toBeVisible();
  const state = await (await request.get(`${API}/api/session/${pointer.sessionId}`)).json();
  expect(state.status).toBe('solved'); expect(state.questionsAsked).toBe(1); expect(state.evaluation.reconstructionScore).toBeNull();
  await page.reload(); await expect(page.getByText('剧情进度（非还原评分）：100%', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('win-honest.png'), fullPage: true });
});

test('429 original-turn recovery stops automatically and waits for manual sync using the same UUID', async ({ page, request }) => {
  let id = ''; let queries = 0; let deadline = 0;
  await page.route(`${API}/api/chat`, async route => {
    const data = route.request().postDataJSON();
    if (!data.question) { await route.continue(); return; }
    id = data.requestId; expect((await route.fetch({ maxRedirects: 0 })).ok()).toBeTruthy(); await route.abort('failed');
  });
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  await input.fill('这封信是在测试限流恢复吗？'); await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Failed to fetch' })).toBeVisible();
  const pattern = `${API}/api/session/*/turns/*`;
  await page.route(pattern, async route => {
    queries++; expect(route.request().url().endsWith(id)).toBe(true); deadline = Date.now() + 1000;
    await route.fulfill({ status: 429, headers: { 'Retry-After': '1' }, json: { code: 'rate_limit' } });
  });
  await page.reload(); await expect(page.getByRole('alert').filter({ hasText: '请求较多' })).toBeVisible();
  expect(queries).toBe(1);
  const journal = await page.evaluate(() => JSON.parse(localStorage.getItem('game_operation_v1:["xin","xuermu"]')!)); expect(journal.operation.requestId).toBe(id);
  await expect.poll(() => Date.now()).toBeGreaterThanOrEqual(deadline + 50); expect(queries).toBe(1);
  await page.unroute(pattern); await page.getByRole('button', { name: '同步原对局' }).click(); await expect(input).toBeEnabled();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  const state = await (await request.get(`${API}/api/session/${saved.sessionId}`)).json(); expect(state.questionsAsked).toBe(1);
});

test('committed response loss and refresh recover original UUID once, without a second charge', async ({ page, request }, info) => {
  let committed = false; let asks = 0; let requestId = ''; const queried: string[] = [];
  await page.route(`${API}/api/session/*/turns/*`, async route => {
    queried.push(route.request().url().split('/').pop()!); await route.continue();
  });
  await page.route(`${API}/api/chat`, async route => {
    const data = route.request().postDataJSON();
    if (data.question) {
      asks++; requestId = data.requestId;
      const result = await route.fetch({ maxRedirects: 0 }); expect(result.ok()).toBeTruthy();
      committed = true; await route.abort('failed'); return;
    }
    await route.continue();
  });
  await page.goto('/game/xin?level=xuermu');
  const input = page.getByRole('textbox', { name: '向主持人提问' }); await expect(input).toBeEnabled();
  await input.fill('这是用来检查断网恢复的吗？'); await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(() => committed).toBe(true); await expect(page.getByRole('alert').filter({ hasText: 'Failed to fetch' })).toBeVisible();
  await expect(page.getByText(/不会扣次数|未扣次数/)).toHaveCount(0);
  const pending = await page.evaluate(() => JSON.parse(localStorage.getItem('game_operation_v1:["xin","xuermu"]')!));
  expect(pending.operation.requestId).toBe(requestId);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  await page.reload(); await expect(input).toBeEnabled();
  expect(queried).toContain(requestId); expect(asks).toBe(1);
  const restored = await (await request.get(`${API}/api/session/${saved.sessionId}`)).json();
  expect(restored.questionsAsked).toBe(1); expect(restored.messages.filter((m: { role: string }) => m.role === 'user')).toHaveLength(1);
  expect(await page.evaluate(() => localStorage.getItem('game_operation_v1:["xin","xuermu"]'))).toBeNull();
  await page.screenshot({ path: info.outputPath('recovered-committed.png'), fullPage: true });
});

test('restoration 503 keeps saved game and manual sync never creates another session', async ({ page }) => {
  let creates = 0;
  await page.route(`${API}/api/chat`, async route => { if (!route.request().postDataJSON().question) creates++; await route.continue(); });
  await page.goto('/game/xin?level=xuermu');
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeEnabled();
  const pointer = await page.evaluate(() => localStorage.getItem('last_session'));
  const pattern = `${API}/api/session/*`;
  await page.route(pattern, route => route.fulfill({ status: 503, json: { code: 'synthetic_outage' } }));
  await page.reload(); await expect(page.getByRole('alert').filter({ hasText: '服务暂时不可用' })).toBeVisible();
  expect(creates).toBe(1); expect(await page.evaluate(() => localStorage.getItem('last_session'))).toBe(pointer);
  await page.unroute(pattern); await page.getByRole('button', { name: '同步原对局' }).click();
  await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeEnabled(); expect(creates).toBe(1);
});

test('lost reveal response restores the immutable ended result through GET before retry', async ({ page, request }, info) => {
  let reveals = 0;
  await page.route(`${API}/api/evaluate`, async route => {
    reveals++; const result = await route.fetch({ maxRedirects: 0 }); expect(result.ok()).toBeTruthy(); await route.abort('failed');
  });
  await page.goto('/game/xin?level=xuermu'); await expect(page.getByRole('textbox', { name: '向主持人提问' })).toBeEnabled();
  const pointer = await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!));
  await page.getByRole('button', { name: '揭晓答案', exact: true }).click(); await expect(page.getByRole('alert').filter({ hasText: 'Failed to fetch' })).toBeVisible();
  const snapshot = await (await request.get(`${API}/api/session/${pointer.sessionId}`)).json();
  expect(snapshot.status).toBe('given_up'); expect(snapshot.evaluation.scoreVersion).toBe('coverage-v1');
  await page.reload(); await expect(page.getByText('完整汤底', { exact: true })).toBeVisible();
  await expect(page.getByText('已确认事实覆盖', { exact: true })).toBeVisible(); await expect(page.getByText('还原程度：尚未独立评估', { exact: true })).toBeVisible();
  expect(reveals).toBe(1);
  const final = await (await request.get(`${API}/api/session/${pointer.sessionId}`)).json(); expect(final.evaluation).toEqual(snapshot.evaluation);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('last_session')!).sessionId)).toBe(pointer.sessionId);
  await page.screenshot({ path: info.outputPath('ended-frozen.png'), fullPage: true });
});

test('legacy ended fixture stays labeled as legacy and never creates a playing game', async ({ page }, info) => {
  const sid = 'synthetic-legacy-only'; let creates = 0;
  await page.addInitScript(sid => localStorage.setItem('last_session', JSON.stringify({ sessionId: sid, soupId: 'xin', level: 'xuermu' })), sid);
  await page.route(`${API}/api/chat`, async route => { creates++; await route.continue(); });
  await page.route(`${API}/api/session/${sid}`, route => route.fulfill({ json: {
    sessionId: sid, soupId: 'xin', soupTitle: '合成旧记录', soupSurface: '浏览器旧格式夹具，不是玩家数据',
    status: 'given_up', questionLimit: 35, questionsAsked: 1, remaining: 34, unlocks: null, messages: [],
    evaluation: { completion: 60, evaluation: '合成旧结果', keyPointsCovered: [], keyPointsMissing: [], bottom: '合成旧汤底' },
  } }));
  await page.goto('/game/xin?level=xuermu');
  await expect(page.getByText('历史分数（旧口径）', { exact: true })).toBeVisible();
  await expect(page.getByText('还原程度：尚未独立评估', { exact: true })).toBeVisible(); expect(creates).toBe(0);
  await page.reload(); await expect(page.getByText('历史分数（旧口径）', { exact: true })).toBeVisible(); expect(creates).toBe(0);
  await page.screenshot({ path: info.outputPath('legacy-honest.png'), fullPage: true });
});
