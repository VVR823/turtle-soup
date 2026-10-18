import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import MetricsPanel from './MetricsPanel';
import { metricsPage, metricsExport, observedMetricsPage } from '../../tests/frontend/metrics-fixtures';
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

test('known observations show complete test cohort without calling zero real activity zero errors', async () => {
  vi.stubGlobal('fetch', async () => response(observedMetricsPage()));
  render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  await screen.findByText('真实发布后复查：0次；尚无真实观测，不代表零错误或质量达标。');
  expect(screen.getByText(/测试复查：4次；反例1次；不完整1次；待完成1次/)).toBeTruthy();
  expect(screen.getByText(/先发布，再复查/)).toBeTruthy();
  expect(screen.getByLabelText('规则版本（业务来源／复查发布目标）')).toBeTruthy();
  expect(screen.queryByText(/0%/)).toBeNull();
});

test.each(['filter', 'token', 'unmount'])('v3 late observation results cannot restore private stats after %s', async cause => {
  let done!: (value: Response) => void;
  vi.stubGlobal('fetch', () => new Promise<Response>(resolve => { done = resolve; }));
  const view = render(<MetricsPanel adminToken="old-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  if (cause === 'filter') fireEvent.change(screen.getByLabelText('题目ID'), { target: { value: 'another' } });
  else if (cause === 'token') view.rerender(<MetricsPanel adminToken="new-admin" />);
  else view.unmount();
  await act(async () => { done(response(observedMetricsPage())); });
  expect(screen.queryByText(/真实发布后复查：/)).toBeNull();
});

test('metrics only query manually, show unknown coverage and full denominator, never poll', async () => {
  const fetcher = vi.fn(async (url: string) => { expect(url).toContain('/api/metrics/admin'); return response(metricsPage()); }); vi.stubGlobal('fetch', fetcher);
  render(<MetricsPanel adminToken="synthetic-admin" />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  await screen.findByText('新建会话：2');
  expect(screen.getByText('尚无任务（分母为0），不显示成功率。')).toBeTruthy();
  expect(screen.getByText(/覆盖情况未知/)).toBeTruthy();
  expect(screen.getByText(/测试、合成、旧数据和来源不明的记录单独列出/)).toBeTruthy();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(String(fetcher.mock.calls[0]?.[0])).not.toContain('start=');
});

test('old token response is aborted and cannot restore private results', async () => {
  let resolve!: (value: Response) => void; let signal: AbortSignal | null | undefined;
  vi.stubGlobal('fetch', (_url: string, init?: RequestInit) => { signal = init?.signal; return new Promise<Response>(done => { resolve = done; }); });
  const view = render(<MetricsPanel adminToken="old-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  view.rerender(<MetricsPanel adminToken="new-admin" />);
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolve(response(metricsPage())); });
  expect(screen.queryByText('新建会话：2')).toBeNull();
});

test('filter change aborts pending query and clears previously shown binding', async () => {
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn().mockResolvedValueOnce(response(metricsPage())).mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  vi.stubGlobal('fetch', fetcher); render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByText('新建会话：2');
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  fireEvent.change(screen.getByLabelText('题目ID'), { target: { value: 'another' } });
  await act(async () => { resolve(response(metricsPage())); });
  expect(screen.queryByText('新建会话：2')).toBeNull();
  expect(screen.getByRole('button', { name: '下载完整统计' }).hasAttribute('disabled')).toBe(true);
});

test.each([401, 429, 503, 409])('safe recoverable HTTP error %s never echoes raw detail', async status => {
  vi.stubGlobal('fetch', async () => response({ detail: 'PRIVATE_DIAGNOSTIC' }, status));
  render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('PRIVATE_DIAGNOSTIC')).toBeNull();
  expect(screen.queryByText('新建会话：2')).toBeNull();
});

test('coverage enum arrays cannot turn unknown metadata into complete coverage on screen', async () => {
  const data = metricsPage(); Object.assign(data.coverage, { state: ['unknown'] });
  vi.stubGlobal('fetch', async () => response(data));
  render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('此刻已知审计覆盖完整')).toBeNull();
  expect(screen.queryByText('新建会话：2')).toBeNull();
});

test('malformed counts cannot show an apparently valid result', async () => {
  const data = metricsPage(); data.summary.counts.sessionsCreated = -1;
  vi.stubGlobal('fetch', async () => response(data)); render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByRole('alert');
  expect(screen.queryByText('新建会话：-1')).toBeNull();
});

test('private stats display missing post-publication source as unknown, never zero', async () => {
  const page = metricsPage();
  const raw = { ...page, schemaVersion: 2, summary: { ...page.summary,
    postPublicationRegression: { state: 'unknown', failedRuns: null, observedRuns: null, reason: 'source_not_integrated' } } };
  vi.stubGlobal('fetch', async () => response(raw)); render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  await screen.findByText(/发布后回归失败：未知/);
  expect(screen.getByText(/可信来源未接入/).textContent).toContain('可信来源未接入');
  expect(screen.queryByText('发布后回归失败：0')).toBeNull();
});

test('complete download uses fixed returned window, strips pagination and revokes the blob', async () => {
  const urls: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => { urls.push(url); return response(url.includes('/export') ? metricsExport() : metricsPage()); });
  const create = vi.fn(() => 'blob:synthetic-metrics'), revoke = vi.fn();
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByText('新建会话：2');
  fireEvent.click(screen.getByRole('button', { name: '下载完整统计' }));
  await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
  expect(urls[1]).toContain('start=1000'); expect(urls[1]).toContain('end=1100');
  expect(urls[1]).not.toContain('limit='); expect(urls[1]).not.toContain('cursor=');
  expect(create).toHaveBeenCalledTimes(1); expect(revoke).toHaveBeenCalledWith('blob:synthetic-metrics');
});

test('double click starts one query and unmount aborts the owned request', () => {
  let signal: AbortSignal | null | undefined;
  const fetcher = vi.fn((_url: string, init?: RequestInit) => { signal = init?.signal; return new Promise<Response>(() => {}); });
  vi.stubGlobal('fetch', fetcher); const view = render(<MetricsPanel adminToken="synthetic-admin" />);
  const button = screen.getByRole('button', { name: '查询统计' }); fireEvent.click(button); fireEvent.click(button);
  expect(fetcher).toHaveBeenCalledTimes(1); view.unmount(); expect(signal?.aborted).toBe(true);
});

test.each((['query', 'next', 'export'] as const).flatMap(mode =>
  (['fetch', 'body'] as const).flatMap(stage => [false, true].map(honorAbort => [mode, stage, honorAbort] as const))))(
  'bounded %s/%s releases controls and fences late results (honor abort=%s)', async (mode, stage, honorAbort) => {
  // Fetch is the unavoidable transport seam; the real panel/decoder own state.
  const initial = metricsPage(); initial.nextCursor = 'encoded';
  vi.stubGlobal('fetch', async () => response(initial));
  const view = render(<MetricsPanel adminToken="synthetic-admin" />);
  if (mode !== 'query') {
    fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
    await screen.findByText('新建会话：2');
  }
  const create = vi.fn(() => 'blob:synthetic-late');
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() });
  vi.useFakeTimers();
  try {
        let releaseFetch!: (value: Response) => void;
        let releaseBody!: (value: unknown) => void;
        vi.stubGlobal('fetch', (_url: string, init?: RequestInit) => {
          const pending = stage === 'fetch' ? new Promise<Response>((resolve, reject) => {
            releaseFetch = resolve;
            if (honorAbort) init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
          }) : Promise.resolve(Object.assign(response(initial), { json: () => new Promise<unknown>((resolve, reject) => {
            releaseBody = resolve;
            if (honorAbort) init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
          }) }));
          return pending;
        });
        const name = { query: '查询统计', next: '下一页统计', export: '下载完整统计' }[mode];
        await act(async () => { fireEvent.click(screen.getByRole('button', { name })); });
        expect(screen.getByRole('button', { name: '查询统计' }).hasAttribute('disabled')).toBe(true);
        await act(async () => { await vi.advanceTimersByTimeAsync(9999); });
        expect(screen.getByText('正在处理统计，请稍候…')).toBeTruthy();
        await act(async () => { await vi.advanceTimersByTimeAsync(1); });
        expect(screen.getByRole('alert').textContent).toContain('超时');
        expect(screen.getByRole('button', { name: '查询统计' }).hasAttribute('disabled')).toBe(false);
        expect(screen.queryByText('正在处理统计，请稍候…')).toBeNull();
        const late = metricsPage(); late.nextCursor = 'encoded';
        late.query.cursor = mode === 'next' ? 'encoded' : null;
        late.summary.counts.sessionsCreated = late.groups[0].counts.sessionsCreated = 99;
        await act(async () => {
          if (stage === 'fetch') releaseFetch(response(mode === 'export' ? metricsExport() : late));
          else releaseBody(mode === 'export' ? metricsExport() : late);
        });
        expect(screen.queryByText('新建会话：99')).toBeNull();
        expect(create).not.toHaveBeenCalled();
        vi.stubGlobal('fetch', async () => response(initial));
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: '查询统计' })); });
        expect(screen.getByText('新建会话：2')).toBeTruthy();
        expect(screen.queryByRole('alert')).toBeNull();
  } finally { view.unmount(); vi.useRealTimers(); }
});

test('returning to an earlier token must not resurrect its old private page', async () => {
  vi.stubGlobal('fetch', async () => response(metricsPage()));
  const view = render(<MetricsPanel adminToken="old-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByText('新建会话：2');
  view.rerender(<MetricsPanel adminToken="new-admin" />);
  expect(screen.queryByText('新建会话：2')).toBeNull();
  view.rerender(<MetricsPanel adminToken="old-admin" />);
  expect(screen.queryByText('新建会话：2')).toBeNull();
});

test('returning to earlier filters needs a fresh query, not stale restored results', async () => {
  vi.stubGlobal('fetch', async () => response(metricsPage()));
  render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByText('新建会话：2');
  fireEvent.change(screen.getByLabelText('题目ID'), { target: { value: 'another' } });
  fireEvent.change(screen.getByLabelText('题目ID'), { target: { value: '' } });
  expect(screen.queryByText('新建会话：2')).toBeNull();
});

test('next page retains actual window even though the clock and live count change', async () => {
  const first = metricsPage(); first.nextCursor = 'encoded';
  const next = metricsPage(); next.query.cursor = 'encoded'; next.summary.counts.sessionsCreated = next.groups[0].counts.sessionsCreated = 3;
  const fetcher = vi.fn().mockResolvedValueOnce(response(first)).mockResolvedValueOnce(response(next));
  vi.stubGlobal('fetch', fetcher); render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByText('新建会话：2');
  fireEvent.click(screen.getByRole('button', { name: '下一页统计' })); await screen.findByText('新建会话：3');
  expect(String(fetcher.mock.calls[1][0])).toContain('start=1000');
  expect(String(fetcher.mock.calls[1][0])).toContain('end=1100');
  expect(String(fetcher.mock.calls[1][0])).toContain('cursor=encoded');
});

test('a valid-looking response for different requested filters is not shown', async () => {
  vi.stubGlobal('fetch', async () => response(metricsPage())); render(<MetricsPanel adminToken="synthetic-admin" />);
  fireEvent.change(screen.getByLabelText('题目ID'), { target: { value: 'synthetic' } });
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByRole('alert');
  expect(screen.queryByText('新建会话：2')).toBeNull();
});

test.each(['filter', 'token', 'unmount'])('late export cannot download after %s changes', async cause => {
  let resolve!: (value: Response) => void; let signal: AbortSignal | null | undefined;
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    if (!url.includes('/export')) return Promise.resolve(response(metricsPage()));
    signal = init?.signal; return new Promise<Response>(done => { resolve = done; });
  });
  const create = vi.fn(); vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() });
  const view = render(<MetricsPanel adminToken="old-admin" />);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByText('新建会话：2');
  fireEvent.click(screen.getByRole('button', { name: '下载完整统计' }));
  if (cause === 'filter') fireEvent.change(screen.getByLabelText('题目ID'), { target: { value: 'another' } });
  else if (cause === 'token') view.rerender(<MetricsPanel adminToken="new-admin" />);
  else view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolve(response(metricsExport())); });
  expect(create).not.toHaveBeenCalled();
});
