import { test, expect, API } from './fixtures';

for (const fault of ['503', '429', 'invalid-json', 'wrong-shape']) {
  test(`config ${fault} fails closed instead of exposing the site`, async ({ page }) => {
    await page.route(`${API}/api/config`, route => route.fulfill(fault === 'invalid-json'
      ? { status: 200, contentType: 'application/json', body: 'not-json' }
      : { status: fault === '503' ? 503 : fault === '429' ? 429 : 200, json: { siteLocked: fault === 'wrong-shape' ? 'no' : false } }));
    await page.goto('/'); await expect(page.getByRole('alert').filter({ hasText: '站点服务暂时不可用' })).toBeVisible();
    await expect(page.getByRole('button', { name: '重新检查站点' })).toBeVisible();
    await expect(page.getByPlaceholder(/搜索/)).toHaveCount(0);
  });
}
for (const status of [401, 429, 503]) {
  test(`prospective unlock ${status} neither saves a token nor opens children`, async ({ page }) => {
    await page.route(`${API}/api/config`, route => route.fulfill({ json: { siteLocked: true } }));
    await page.route(`${API}/api/soups**`, route => route.fulfill({ status, json: { detail: 'synthetic verification failure' }, headers: { 'Retry-After': '1' } }));
    await page.goto('/'); await page.getByRole('textbox', { name: '访问口令' }).fill('synthetic-not-real');
    await page.getByRole('button', { name: '进入', exact: true }).click(); await expect(page.getByRole('alert').filter({ hasText: /口令错误|验证未完成/ })).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('site_token'))).toBeNull();
    await expect(page.getByPlaceholder(/搜索/)).toHaveCount(0);
  });
}
test('catalog failure is an error, not an empty or missing-soup success', async ({ page }) => {
  await page.route(`${API}/api/soups**`, route => route.fulfill({ status: 503, json: {} }));
  await page.goto('/'); await expect(page.getByRole('alert').filter({ hasText: '服务暂时不可用' })).toBeVisible();
  await expect(page.getByText(/没有找到符合/)).toHaveCount(0);
  await page.goto('/difficulty/xin'); await expect(page.getByRole('alert').filter({ hasText: '服务暂时不可用' })).toBeVisible();
  await expect(page.getByText('没有找到这道汤哦~')).toHaveCount(0);
});
test('feedback uses the public unlocked list without exposing hidden truth', async ({ page, request }, info) => {
  await page.addInitScript(() => localStorage.setItem('unlocked_soups', JSON.stringify(['xinshijie'])));
  await page.goto('/'); await page.getByRole('button', { name: '主持人答错了？点此提交反馈' }).click();
  const select = page.getByRole('combobox', { name: '选择反馈汤品' });
  await expect(select.locator('option[value="xinshijie"]')).toHaveText('新世界');
  const locked = await (await request.get(`${API}/api/soups`)).json(); expect(locked.soups.some((s: { id: string }) => s.id === 'xinshijie')).toBe(false);
  const publicList = await (await request.get(`${API}/api/soups?unlocked=xinshijie`)).json();
  expect(publicList.soups.some((s: { id: string }) => s.id === 'xinshijie')).toBe(true);
  expect(JSON.stringify(publicList)).not.toMatch(/"(?:bottom|keyFacts|hostResult|confirmed_fact_ids)"/);
  await page.screenshot({ path: info.outputPath('feedback-public-unlocked.png'), fullPage: true });
});
test('fixed UI test CORS accepts only the owned frontend origin', async ({ request }) => {
  const owned = await request.get(`${API}/api/config`, { headers: { Origin: 'http://127.0.0.1:18081' } });
  expect(owned.headers()['access-control-allow-origin']).toBe('http://127.0.0.1:18081');
  const foreign = await request.get(`${API}/api/config`, { headers: { Origin: 'https://example.com' } });
  expect(foreign.headers()['access-control-allow-origin']).toBeUndefined();
});
