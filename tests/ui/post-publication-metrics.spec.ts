import { test, expect, API } from './fixtures';
import { observedMetricsPage } from '../frontend/metrics-fixtures';

// Real Edge UI with declared synthetic response bodies. This exercises the
// browser consumer/layout, not backend publication authority or real traffic.
for (const partial of [false, true]) {
  test(`declared synthetic v3 ${partial ? 'partial' : 'observed'} statistics stay readable at 375px`, async ({ page }, info) => {
    const requests: string[] = [], errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem('turtle_admin_token', 'e2e-test-only'));
    await page.route(`${API}/api/metrics/admin?**`, async route => {
      requests.push(route.request().url());
      const parameters = new URL(route.request().url()).searchParams;
      const fixture = observedMetricsPage();
      fixture.query.start = Number(parameters.get('start'));
      fixture.query.end = Number(parameters.get('end'));
      fixture.groups[0].day = new Date(fixture.query.start * 1000).toISOString().slice(0, 10);
      const value = fixture.summary.postPublicationRegression;
      value.sourceCoverageStart = fixture.query.start + (partial ? 60 : 0);
      const body = { ...fixture, summary: { ...fixture.summary, postPublicationRegression: {
        ...value, state: partial ? 'partial' : 'observed', windowStartsBeforeCoverage: partial,
      } } };
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/admin/feedback');
    const panel = page.getByRole('region', { name: '运行统计（私有）' });
    await expect(panel.getByRole('button', { name: '查询统计' })).toBeVisible();
    expect(requests).toHaveLength(0);
    await panel.getByLabel('开始时间（UTC）').fill('2026-10-12T00:00');
    await panel.getByLabel('结束时间（UTC）').fill('2026-10-13T00:00');
    await panel.getByRole('button', { name: '查询统计' }).click();
    await expect(panel.getByText('真实发布后复查：0次；尚无真实观测，不代表零错误或质量达标。', { exact: true })).toBeVisible();
    await expect(panel.getByText(/测试复查：4次；反例1次；不完整1次；待完成1次/)).toBeVisible();
    await expect(panel.getByText(/发现反例是答错；执行异常、未支持或没检查完是另一回事/)).toBeVisible();
    await expect(panel.getByText(partial ? /区间含启用前缺口/ : /区间在观测启用后/)).toBeVisible();
    expect(requests).toHaveLength(1);
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth }));
    expect(dimensions.viewport).toBe(375); expect(dimensions.width).toBeLessThanOrEqual(375);
    await page.screenshot({ path: info.outputPath(`synthetic-v3-${partial ? 'partial' : 'observed'}-mobile.png`), fullPage: true });
    await panel.getByLabel('题目ID').fill('synthetic');
    await expect(panel.getByRole('button', { name: '下载完整统计' })).toBeDisabled();
    await expect(panel.getByText(/真实发布后复查：0次/)).toHaveCount(0);
    expect(requests).toHaveLength(1); expect(errors).toEqual([]);
  });
}
