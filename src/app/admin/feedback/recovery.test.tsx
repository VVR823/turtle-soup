import { act, fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import AdminFeedbackPage from './page';

const row = { id: 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', ts: '2026-10-09T00:00:00Z',
  soupId: 'synthetic', soupTitle: '合成题目', question: '合成问题', hostAnswer: '是', expectedAnswer: '不是',
  reason: null, status: 'pending', reviewedAt: null, mergedAt: null, mergedAnswer: null,
  rowVersion: 3, safeForModel: false, sourceState: 'unverified', turnId: null };
const page = { feedbacks: [row], totalInRange: 2, nextCursor: 'owned_cursor' };
const response = (value: unknown) => new Response(JSON.stringify(value));

test('blocked credential storage explains the failure without sending a private request', () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  const blocked = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('blocked', 'QuotaExceededError'); });
  try {
    render(<AdminFeedbackPage />);
    fireEvent.change(screen.getByPlaceholderText('管理口令'), { target: { value: 'synthetic-admin' } });
    fireEvent.click(screen.getByRole('button', { name: '进入' }));
    expect(screen.getByText(/无法保存管理口令/)).toBeTruthy(); expect(fetch).not.toHaveBeenCalled();
  } finally { blocked.mockRestore(); }
});

test.each(['fetch', 'body'] as const)('a hanging list %s releases refresh and ignores its late private result', async kind => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  let finish!: (value: never) => void;
  const hanging = new Promise<never>(resolve => { finish = resolve; });
  const fetch = vi.fn().mockImplementationOnce(() => kind === 'fetch' ? hanging : Promise.resolve({ ok: true, json: () => hanging }))
    .mockResolvedValue(response({ ...page, feedbacks: [{ ...row, question: '新的反馈' }] }));
  vi.stubGlobal('fetch', fetch); vi.useFakeTimers();
  const view = render(<AdminFeedbackPage />);
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(30001); });
    expect(screen.getByText(/加载超时/)).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '刷新' })); });
    expect(screen.getByText('新的反馈')).toBeTruthy();
    await act(async () => { finish((kind === 'fetch' ? response(page) : page) as never); });
    expect(screen.queryByText('合成问题')).toBeNull(); expect(fetch).toHaveBeenCalledTimes(2);
  } finally { view.unmount(); vi.useRealTimers(); }
});

test.each(['fetch', 'body'] as const)('an uncertain review %s times out without retry or inventing approval', async kind => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  let finish!: (value: never) => void;
  const hanging = new Promise<never>(resolve => { finish = resolve; });
  const fetch = vi.fn(async (_url: string, init?: RequestInit) => init?.method === 'POST'
    ? kind === 'fetch' ? hanging : { ok: true, json: () => hanging } : response(page));
  vi.stubGlobal('fetch', fetch); render(<AdminFeedbackPage />);
  await screen.findByRole('button', { name: '确认反馈有效' });
  vi.useFakeTimers();
  try {
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '确认反馈有效' })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(30001); });
    expect(screen.getByText(/审核请求超时.*可能已经提交/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '刷新' }).hasAttribute('disabled')).toBe(false);
    const calls = fetch.mock.calls.length;
    await act(async () => { finish((kind === 'fetch' ? response({ ok: true, feedback: { ...row, status: 'approved', rowVersion: 4 } }) : { ok: true, feedback: { ...row, status: 'approved', rowVersion: 4 } }) as never); });
    expect(screen.getByText('审核版本：3')).toBeTruthy(); expect(fetch).toHaveBeenCalledTimes(calls);
  } finally { vi.useRealTimers(); }
});

test('pending badge explicitly counts only loaded pages', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  vi.stubGlobal('fetch', async () => response({ ...page, feedbacks: [{ ...row, status: 'rejected', reviewedAt: row.ts }] }));
  render(<AdminFeedbackPage />); await screen.findByText('合成问题');
  expect(screen.getByText('已加载中 0 条待处理')).toBeTruthy();
  expect(screen.getByRole('button', { name: '加载更多' })).toBeTruthy();
});

test('historical feedback queries bind inclusive Beijing dates and reuse that window when paging', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin'); const urls: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => { urls.push(url); return response(page); });
  render(<AdminFeedbackPage />); await screen.findByText('合成问题');
  fireEvent.change(screen.getByLabelText('反馈开始日期'), { target: { value: '2026-08-01' } });
  fireEvent.change(screen.getByLabelText('反馈结束日期'), { target: { value: '2026-08-31' } });
  fireEvent.click(screen.getByRole('button', { name: '查询历史反馈' }));
  await screen.findByText(/2026-08-01 至 2026-08-31.*共 2 条/);
  fireEvent.click(screen.getByRole('button', { name: '加载更多' }));
  await act(async () => {});
  const range = new URL(urls[1]).searchParams, next = new URL(urls[2]).searchParams;
  expect(Number(range.get('start'))).toBe(Date.parse('2026-08-01T00:00:00+08:00') / 1000);
  expect(Number(range.get('end'))).toBe(Date.parse('2026-09-01T00:00:00+08:00') / 1000);
  expect(next.get('start')).toBe(range.get('start')); expect(next.get('end')).toBe(range.get('end'));
  expect(next.get('cursor')).toBe('owned_cursor');
  fireEvent.change(screen.getByLabelText('反馈结束日期'), { target: { value: '2026-09-01' } });
  fireEvent.click(screen.getByRole('button', { name: '查询历史反馈' }));
  expect(screen.getByText(/每次最多查询31天/)).toBeTruthy(); expect(urls).toHaveLength(3);
});
