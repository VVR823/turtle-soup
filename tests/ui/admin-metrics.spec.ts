import { test, expect, API } from './fixtures';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

test('owned real browser: manual stats, source paging, full download and test exclusion', async ({ page, request }, info) => {
  test.setTimeout(35_000);
  const root = process.cwd(), backend = path.join(root, 'backend');
  const python = path.join(backend, '.venv-ts01', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  // Existing auto fixture already verified live health against the exact nonce.
  // Preparation additionally checks that same nonce in preexisting SQLite;
  // these105 real-tagged rows are DECLARED SYNTHETIC, never actual users.
  const volume = JSON.parse(execFileSync(python, ['-m', 'testing.metrics_ui_fixture'], {
    cwd: backend, env: process.env, timeout: 10_000, encoding: 'utf8', windowsHide: true,
  }));
  expect(volume.evidenceKind).toBe('declared_synthetic_ui_volume'); expect(volume.sessionRows).toBe(105);
  expect((await request.get(`${API}/api/metrics/admin`)).status()).toBe(401);
  const created = await request.post(`${API}/api/chat`, { data: { soupId: 'synthetic-ui', requestId: randomUUID() } });
  expect(created.ok()).toBeTruthy(); const privateSession = (await created.json()).sessionId;
  const uncaught: string[] = [], consoleErrors: string[] = [], statsRequests: string[] = [];
  page.on('pageerror', error => uncaught.push(error.message));
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('request', request => { if (request.url().startsWith(`${API}/api/metrics/admin`)) statsRequests.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem('turtle_admin_token', 'e2e-test-only'));
  await page.goto('/admin/feedback');
  const panel = page.getByRole('region', { name: '运行统计（私有）' });
  await expect(panel.getByRole('button', { name: '查询统计' })).toBeVisible();
  expect(statsRequests).toHaveLength(0); // No statistics polling on mount.
  // Chromium canonicalizes zero seconds to minute precision; Playwright's fill
  // checks the normalized value. Use that normal input form, not :00 seconds.
  await panel.getByLabel('开始时间（UTC）').fill(new Date(volume.start * 1000).toISOString().slice(0, 16));
  await panel.getByLabel('结束时间（UTC）').fill(new Date(Date.now() + 60_000).toISOString().slice(0, 16));
  const firstResponse = page.waitForResponse(response => response.url().startsWith(`${API}/api/metrics/admin?`));
  await panel.getByRole('button', { name: '查询统计' }).click();
  const first = await (await firstResponse).json();
  const missingSource = { state: 'unknown', failedRuns: null, observedRuns: null, reason: 'schema_5_required' };
  expect(first.schemaVersion).toBe(3);
  expect(first.summary.postPublicationRegression).toEqual(missingSource);
  expect(first.groups).toHaveLength(50); expect(first.summary.counts.sessionsCreated).toBe(105);
  expect(first.summary.excluded.test.sessionsCreated).toBeGreaterThan(0);
  await expect(panel.getByText('新建会话：105', { exact: true })).toBeVisible();
  await expect(panel.getByText(/发布后回归失败：未知/)).toBeVisible();
  await expect(panel.getByText(/尚未启用005观测账本/)).toBeVisible();
  await expect(panel.getByText('发布后回归失败：0', { exact: true })).toHaveCount(0);
  const allKeys = first.groups.map((group: Record<string, unknown>) => JSON.stringify([group.day, group.soupId, group.puzzleVersion, group.ruleVersion]));
  for (const expectedSize of [50, 5]) {
    const nextResponse = page.waitForResponse(response => response.url().startsWith(`${API}/api/metrics/admin?`) && response.url().includes('cursor='));
    await panel.getByRole('button', { name: '下一页统计' }).click();
    const next = await (await nextResponse).json();
    expect(next.schemaVersion).toBe(3);
    expect(next.summary.postPublicationRegression).toEqual(missingSource);
    expect(next.query.start).toBe(first.query.start); expect(next.query.end).toBe(first.query.end);
    expect(next.groups).toHaveLength(expectedSize);
    allKeys.push(...next.groups.map((group: Record<string, unknown>) => JSON.stringify([group.day, group.soupId, group.puzzleVersion, group.ruleVersion])));
    await expect(panel.locator('caption').filter({ hasText: `本页公开来源分组（${expectedSize}组）` })).toBeVisible();
  }
  expect(new Set(allKeys).size).toBe(105); await expect(panel.getByRole('button', { name: '下一页统计' })).toBeDisabled();
  await panel.getByRole('button', { name: '下载完整统计' }).click();
  await expect(panel.getByRole('alert')).toHaveText('完整导出超过上限，请缩小时间、题目或版本范围。');
  await panel.getByLabel('题目ID').fill(volume.firstSoupId);
  await expect(panel.getByRole('button', { name: '下载完整统计' })).toBeDisabled();
  await panel.getByRole('button', { name: '查询统计' }).click();
  await expect(panel.getByText('新建会话：27', { exact: true })).toBeVisible();
  const downloadEvent = page.waitForEvent('download');
  await panel.getByRole('button', { name: '下载完整统计' }).click();
  const download = await downloadEvent; expect(download.suggestedFilename()).toBe('turtle-soup-metrics.json');
  const output = info.outputPath('metrics-complete.json'); await download.saveAs(output);
  const raw = fs.readFileSync(output, 'utf8'), exported = JSON.parse(raw);
  expect(exported.complete).toBe(true); expect(exported.groups).toHaveLength(27);
  expect(exported.schemaVersion).toBe(3);
  expect(exported.summary.postPublicationRegression).toEqual(missingSource);
  expect(exported.summary.counts.sessionsCreated).toBe(27);
  expect(exported.groups.reduce((total: number, group: { counts: { sessionsCreated: number } }) => total + group.counts.sessionsCreated, 0)).toBe(27);
  expect(exported.filters.soupId).toBe(volume.firstSoupId); expect(exported.nextCursor).toBeUndefined();
  expect(raw).not.toContain(privateSession); expect(raw).not.toContain('e2e-test-only');
  expect(raw).not.toContain('rawQuestion'); expect(Buffer.byteLength(raw)).toBeLessThanOrEqual(512 * 1024);
  await page.screenshot({ path: info.outputPath('metrics-complete-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(panel.getByText(/发布后回归失败：未知/)).toBeVisible();
  await expect(panel.getByRole('button', { name: '查询统计' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('metrics-complete-mobile.png'), fullPage: true });
  await page.screenshot({ path: info.outputPath('metrics-mobile-viewport.png') });
  const groupingTable = panel.getByRole('table', { name: '本页公开来源分组（27组）', exact: true });
  const readability = await groupingTable.evaluate(table => {
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    const versionCells = rows.flatMap(row => [row.children[2], row.children[3]]);
    const frame = table.parentElement!;
    const bounds = frame.getBoundingClientRect();
    return { rows: rows.length, minVersionWidth: Math.min(...versionCells.map(cell => cell.getBoundingClientRect().width)),
      minDateWidth: Math.min(...rows.map(row => row.children[0].getBoundingClientRect().width)),
      maxRowHeight: Math.max(...rows.map(row => row.getBoundingClientRect().height)),
      frame: { left: bounds.left, right: bounds.right, clientWidth: frame.clientWidth, scrollWidth: frame.scrollWidth } };
  });
  fs.writeFileSync(info.outputPath('metrics-mobile-readability.json'), JSON.stringify(readability), { flag: 'wx' });
  expect(readability.rows).toBe(27);
  expect(readability.minVersionWidth).toBeGreaterThanOrEqual(240);
  expect(readability.minDateWidth).toBeGreaterThanOrEqual(80);
  expect(readability.maxRowHeight).toBeLessThanOrEqual(100);
  expect(readability.frame.left).toBeGreaterThanOrEqual(0);
  expect(readability.frame.right).toBeLessThanOrEqual(375.5);
  expect(readability.frame.scrollWidth).toBeGreaterThan(readability.frame.clientWidth);
  const scrollFrame = panel.getByRole('region', { name: '来源分组表（横向滚动）', exact: true });
  await scrollFrame.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(() => scrollFrame.evaluate(frame => frame.scrollLeft)).toBeGreaterThan(0);
  await scrollFrame.evaluate(frame => { frame.scrollLeft = 0; });
  await expect(groupingTable.getByRole('cell', { name: exported.groups[0].puzzleVersion, exact: true })).toHaveCount(27);
  await expect(groupingTable.getByRole('cell', { name: exported.groups[0].ruleVersion, exact: true })).toHaveCount(27);
  const layout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth,
    outside: Array.from(document.querySelectorAll('input,select,table,section')).map(element => {
      const rect = element.getBoundingClientRect();
      if (element.tagName === 'TABLE') {
        const frame = element.parentElement!;
        const clip = frame.getBoundingClientRect();
        // A wide table is valid only inside a genuinely clipped, bounded scroller.
        if (['auto', 'scroll'].includes(getComputedStyle(frame).overflowX) && clip.left >= 0 && clip.right <= innerWidth + 0.5) return null;
      }
      return { tag: element.tagName, classes: element.className, left: rect.left, right: rect.right, width: rect.width };
    }).filter(rect => rect !== null && rect.right > innerWidth + 0.5) }));
  fs.writeFileSync(info.outputPath('metrics-mobile-layout.json'), JSON.stringify(layout));
  expect(layout.document).toBeLessThanOrEqual(layout.viewport);
  fs.writeFileSync(info.outputPath('metrics-console.json'), JSON.stringify({ uncaught, consoleErrors,
    expectedRefusals: ['409 full105groups'], evidenceKind: volume.evidenceKind }));
  expect(uncaught).toEqual([]);
});
