import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import MetricsPanel from './MetricsPanel';
import { metricsPage, metricsExport, observedMetricsPage, observationCounts } from '../../tests/frontend/metrics-fixtures';

const response = (body: unknown, status = 200, headers?: HeadersInit) => new Response(JSON.stringify(body), { status, headers });
const query = () => fireEvent.click(screen.getByRole('button', { name: '查询统计' }));

test.each(['12', '', 'private', '1234567'])('rate-limit hints accept only bounded numeric Retry-After: %j', async retry => {
  vi.stubGlobal('fetch', async () => response({ detail: 'PRIVATE' }, 429, { 'Retry-After': retry }));
  render(<MetricsPanel adminToken="synthetic" />); query();
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toBe('请求较频繁，请稍后重试。' + (retry === '12' ? '建议等待12秒。' : ''));
});

test.each([422, 500])('HTTP %i shows a safe failure without returning private server details', async status => {
  vi.stubGlobal('fetch', async () => response({ detail: 'PRIVATE' }, status));
  render(<MetricsPanel adminToken="synthetic" />); query();
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain(status === 422 ? '查询格式或范围' : '统计请求失败');
  expect(alert.textContent).not.toContain('PRIVATE');
});

test.each(['schema_5_required', 'source_unavailable'])('missing observation reason %s remains unknown on screen', async reason => {
  const page = metricsPage();
  page.schemaVersion = 3; page.summary.postPublicationRegression.reason = reason;
  vi.stubGlobal('fetch', async () => response(page));
  render(<MetricsPanel adminToken="synthetic" />); query();
  await screen.findByText(new RegExp(reason === 'schema_5_required' ? '尚未启用005观测账本' : '来源暂时无法核验'));
  expect(screen.queryByText('发布后回归失败：0')).toBeNull();
});

test.each(['complete', 'partial'])('business audit coverage %s retains the process gap details', async state => {
  const page = metricsPage();
  Object.assign(page.coverage, { state, auditStartedAt: 900, agentStartedAt: 950,
    windowStartsBeforeAudit: false, windowStartsBeforeAgent: false,
    processAudit: { complete: state === 'complete', permanentGap: state !== 'complete',
      dropped: state === 'complete' ? 0 : 3, fallbackCount: 0, memoryCount: 0, activeIO: 0 } });
  page.summary.counts.tasksCreated = 2; page.summary.taskStates.awaiting_review = 2;
  page.summary.taskPublication = { numerator: 1, denominator: 2, ratio: 0.5 };
  vi.stubGlobal('fetch', async () => response(page));
  render(<MetricsPanel adminToken="synthetic" />); query();
  await screen.findByText(/任务发布比例：1\/2（50.0%）；这不是修复正确率/);
  expect(screen.getByText(new RegExp(state === 'complete' ? '此刻已接入事件的审计覆盖完整' : '存在历史或待落盘审计缺口'))).toBeDefined();
  expect(screen.getByText(new RegExp('永久缺口' + (state === 'complete' ? '无' : '有')))).toBeDefined();
});

test('nonzero observations preserve failed, incomplete and pending runs in a partial coverage window', async () => {
  const page = observedMetricsPage();
  Object.assign(page.summary.postPublicationRegression, observationCounts(), {
    state: 'partial', sourceCoverageStart: 1050, windowStartsBeforeCoverage: true,
  });
  vi.stubGlobal('fetch', async () => response(page));
  render(<MetricsPanel adminToken="synthetic" />); query();
  await screen.findByText(/真实发布后复查：4次；通过1次；反例1次；不完整1次；待完成1次/);
  expect(screen.getByText(/区间含启用前缺口，不能当作完整历史/)).toBeDefined();
});

test('unknown group dimensions and an empty next page remain explicit', async () => {
  const initial = metricsPage(); initial.nextCursor = 'owned_cursor';
  initial.groups[0].soupId = initial.groups[0].puzzleVersion = initial.groups[0].ruleVersion = null;
  const next = metricsPage(); next.groups = []; next.query.cursor = 'owned_cursor';
  const fetch = vi.fn().mockResolvedValueOnce(response(initial)).mockResolvedValueOnce(response(next));
  vi.stubGlobal('fetch', fetch); render(<MetricsPanel adminToken="synthetic" />); query();
  await screen.findByText('新建会话：2');
  expect(screen.getAllByText('未知', { exact: true })).toHaveLength(3);
  fireEvent.click(screen.getByRole('button', { name: '下一页统计' }));
  await screen.findByText('当前区间没有明确真实流量的分组。');
  expect(String(fetch.mock.calls[1][0])).toContain('cursor=owned_cursor');
  expect((screen.getByRole('button', { name: '下一页统计' }) as HTMLButtonElement).disabled).toBe(true);
});

test('an explicit UTC window and source filters are trimmed, bound and preserved in the complete export', async () => {
  const page = metricsPage();
  Object.assign(page.query, { soupId: 'synthetic', puzzleVersion: page.groups[0].puzzleVersion,
    ruleVersion: page.groups[0].ruleVersion, limit: 100 });
  const exported = metricsExport();
  Object.assign(exported.filters, { soupId: page.query.soupId, puzzleVersion: page.query.puzzleVersion, ruleVersion: page.query.ruleVersion });
  const calls: Array<[string, RequestInit | undefined]> = [];
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    calls.push([url, init]); return response(url.includes('/export') ? exported : page);
  });
  const create = vi.fn(() => 'blob:synthetic'); const revoke = vi.fn();
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  render(<MetricsPanel adminToken="synthetic" />);
  for (const [label, value] of [['开始时间（UTC）', '1970-01-01T00:16:40'], ['结束时间（UTC）', '1970-01-01T00:18:20'],
    ['题目ID', ' synthetic '], ['来源题目版本', page.query.puzzleVersion!], ['规则版本（业务来源／复查发布目标）', page.query.ruleVersion!]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.change(screen.getByLabelText('每页分组数'), { target: { value: '100' } }); query();
  await screen.findByText('新建会话：2');
  expect(calls[0][0]).toContain('start=1000'); expect(calls[0][0]).toContain('end=1100');
  expect(calls[0][0]).toContain('soupId=synthetic'); expect(calls[0][1]?.headers).toEqual({ 'X-Admin-Token': 'synthetic' });
  fireEvent.click(screen.getByRole('button', { name: '下载完整统计' }));
  await screen.findByText(/已下载完整统计/);
  expect(calls[1][0]).toContain('soupId=synthetic'); expect(calls[1][0]).not.toContain('limit=');
  expect(create).toHaveBeenCalledTimes(1); expect(revoke).toHaveBeenCalledWith('blob:synthetic');
});

test.each(['window', 'filter'])('a coherent export with a foreign %s cannot trigger a download', async kind => {
  const exported = metricsExport();
  if (kind === 'window') exported.window.end += 1;
  else { exported.filters.soupId = 'foreign'; exported.groups[0].soupId = 'foreign'; }
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('/export') ? exported : metricsPage()));
  const create = vi.fn(); vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() });
  render(<MetricsPanel adminToken="synthetic" />); query(); await screen.findByText('新建会话：2');
  fireEvent.click(screen.getByRole('button', { name: '下载完整统计' }));
  await screen.findByRole('alert'); expect(create).not.toHaveBeenCalled();
});

test.each(['soupId', 'puzzleVersion', 'ruleVersion', 'limit', 'start', 'end'] as const)(
  'a syntactically valid page with foreign query %s cannot restore results', async field => {
    const page = metricsPage();
    const values = { soupId: 'foreign', puzzleVersion: 'p1:' + 'c'.repeat(64), ruleVersion: 'r1:' + 'd'.repeat(64),
      limit: 100, start: 1001, end: 1101 };
    Object.assign(page.query, { [field]: values[field] });
    // Keep groups internally coherent, so binding verification is the rejection boundary.
    if (field === 'soupId' || field === 'puzzleVersion' || field === 'ruleVersion') Object.assign(page.groups[0], { [field]: values[field] });
    vi.stubGlobal('fetch', async () => response(page));
    render(<MetricsPanel adminToken="synthetic" />);
    if (field === 'start' || field === 'end') fireEvent.change(screen.getByLabelText(field === 'start' ? '开始时间（UTC）' : '结束时间（UTC）'),
      { target: { value: field === 'start' ? '1970-01-01T00:16:40' : '1970-01-01T00:18:20' } });
    else if (field !== 'limit') fireEvent.change(screen.getByLabelText({ soupId: '题目ID', puzzleVersion: '来源题目版本', ruleVersion: '规则版本（业务来源／复查发布目标）' }[field]),
      { target: { value: field === 'soupId' ? 'synthetic' : metricsPage().groups[0][field]! } });
    query(); await screen.findByRole('alert'); expect(screen.queryByText('新建会话：2')).toBeNull();
  },
);

test('a rejected old request cannot resurrect an error after the filter changes', async () => {
  let reject!: (reason: Error) => void;
  vi.stubGlobal('fetch', () => new Promise<Response>((_done, fail) => { reject = fail; }));
  render(<MetricsPanel adminToken="synthetic" />); query();
  fireEvent.change(screen.getByLabelText('题目ID'), { target: { value: 'another' } });
  await act(async () => reject(new Error('PRIVATE_OLD_ERROR')));
  expect(screen.queryByRole('alert')).toBeNull();
});

test('a failed anchor click still revokes its owned blob and removes its temporary link', async () => {
  vi.stubGlobal('fetch', async (url: string) => response(url.includes('/export') ? metricsExport() : metricsPage()));
  const revoke = vi.fn(); vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:synthetic'), revokeObjectURL: revoke });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { throw new Error('synthetic download denied'); });
  render(<MetricsPanel adminToken="synthetic" />); query(); await screen.findByText('新建会话：2');
  fireEvent.click(screen.getByRole('button', { name: '下载完整统计' }));
  await screen.findByRole('alert');
  await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:synthetic'));
  expect(document.querySelector('a[download]')).toBeNull();
});
