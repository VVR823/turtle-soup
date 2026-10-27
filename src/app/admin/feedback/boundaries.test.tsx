import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import AdminFeedbackPage from './page';

const id = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
const otherId = 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb';
const row = () => ({ id, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: '合成题目', question: '合成问题一',
  hostAnswer: '是', expectedAnswer: '不是', reason: null, status: 'pending', reviewedAt: null, mergedAt: null,
  mergedAnswer: null, rowVersion: 3, safeForModel: false, sourceState: 'unverified', turnId: null });
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const page = (feedbacks = [row()], nextCursor: string | null = null) => ({ feedbacks, totalInRange: feedbacks.length, nextCursor });
function login() { localStorage.setItem('turtle_admin_token', 'synthetic-admin'); }

test('blank credentials and non-Enter keypresses make no private request; Enter submits a trimmed token', async () => {
  const fetch = vi.fn(async () => response(page())); vi.stubGlobal('fetch', fetch); render(<AdminFeedbackPage />);
  fireEvent.click(screen.getByRole('button', { name: '进入' })); expect(fetch).not.toHaveBeenCalled();
  const input = screen.getByPlaceholderText('管理口令');
  fireEvent.change(input, { target: { value: ' synthetic-admin ' } });
  fireEvent.keyDown(input, { key: 'ArrowRight' }); expect(fetch).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: 'Enter' }); await screen.findByText('合成问题一');
  expect(localStorage.getItem('turtle_admin_token')).toBe('synthetic-admin');
});

test('an initial 401 clears the rejected credential and returns a usable login form', async () => {
  login(); vi.stubGlobal('fetch', async () => response({ detail: 'PRIVATE' }, 401)); render(<AdminFeedbackPage />);
  await screen.findByPlaceholderText('管理口令');
  expect(screen.getByText('管理口令错误，请重新输入')).toBeDefined();
  expect(localStorage.getItem('turtle_admin_token')).toBeNull(); expect(screen.queryByText('PRIVATE')).toBeNull();
});

test.each(['http', 'network'])('initial %s failure leaves an explicit refresh path', async mode => {
  login(); const fetch = vi.fn().mockImplementationOnce(() => mode === 'http' ? Promise.resolve(response({}, 500)) : Promise.reject(new Error('PRIVATE')))
    .mockImplementation(async () => response(page())); vi.stubGlobal('fetch', fetch); render(<AdminFeedbackPage />);
  await screen.findByText(mode === 'http' ? '加载失败（500）' : '网络错误，请确认后端已启动');
  fireEvent.click(screen.getByRole('button', { name: '刷新' })); await screen.findByText('合成问题一');
  expect(fetch).toHaveBeenCalledTimes(2);
});

test('soup and status filters combine locally, including title fallback and a genuinely empty match', async () => {
  login(); const second = { ...row(), id: otherId, soupId: 'title-fallback', soupTitle: null, question: '合成问题二', status: 'rejected', reviewedAt: '2026-10-09T00:01:00Z' };
  vi.stubGlobal('fetch', async () => response(page([row(), second] as ReturnType<typeof row>[])));
  render(<AdminFeedbackPage />); await screen.findByText('合成问题二');
  const soups = screen.getByRole('option', { name: '全部汤' }).closest('select')!;
  const statuses = screen.getByRole('option', { name: '全部状态' }).closest('select')!;
  fireEvent.change(soups, { target: { value: 'title-fallback' } });
  expect(screen.queryByText('合成问题一')).toBeNull(); expect(screen.getByText('合成问题二')).toBeDefined();
  fireEvent.change(statuses, { target: { value: 'pending' } }); expect(screen.getByText('没有符合条件的反馈。')).toBeDefined();
  fireEvent.change(soups, { target: { value: '' } }); expect(screen.getByText('合成问题一')).toBeDefined();
  fireEvent.change(statuses, { target: { value: 'rejected' } }); expect(screen.getByText('合成问题二')).toBeDefined();
});

test('a validated empty response states no feedback rather than a filtered empty result', async () => {
  login(); vi.stubGlobal('fetch', async () => response(page([]))); render(<AdminFeedbackPage />);
  await screen.findByText('还没有玩家提交反馈。'); expect(screen.queryByText('没有符合条件的反馈。')).toBeNull();
});

test.each([2, 3, 4])('pagination merges a duplicate identity using rowVersion rather than arrival order: %i', async incomingVersion => {
  login(); const incoming = { ...row(), rowVersion: incomingVersion, question: '分页返回的同一条问题' };
  const fetch = vi.fn().mockResolvedValueOnce(response(page([row()], 'owned_cursor'))).mockResolvedValueOnce(response(page([incoming])));
  vi.stubGlobal('fetch', fetch); render(<AdminFeedbackPage />); await screen.findByText('合成问题一');
  fireEvent.click(screen.getByRole('button', { name: '加载更多' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: '加载更多' })).toBeNull());
  expect(screen.getByText(incomingVersion >= 3 ? '分页返回的同一条问题' : '合成问题一')).toBeDefined();
  expect(screen.getAllByText(/审核版本：/)).toHaveLength(1);
  expect(screen.getByText('审核版本：' + Math.max(3, incomingVersion))).toBeDefined();
});

test.each([{ action: '确认反馈有效', status: 401, message: '管理口令已失效，请重新登录' },
  { action: '确认反馈有效', status: 500, message: '通过失败（500）' },
  { action: '不采纳', status: 500, message: '拒绝失败（500）' }])(
  'review $action HTTP$status cannot invent the next row version', async ({ action, status, message }) => {
    login(); vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => init?.method === 'POST' ? response({ detail: 'PRIVATE' }, status) : response(page()));
    render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: action }));
    await screen.findByText(message); expect(screen.getByText('审核版本：3')).toBeDefined();
    expect(screen.queryByText('审核版本：4')).toBeNull(); expect(screen.queryByText('PRIVATE')).toBeNull();
  },
);

test('a network failure during review preserves the row and permits a fresh explicit decision', async () => {
  login(); vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') throw new Error('PRIVATE'); return response(page());
  });
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await screen.findByText('网络错误，操作结果未确认，可能已经提交；请先刷新核对');
  expect((screen.getByRole('button', { name: '确认反馈有效' }) as HTMLButtonElement).disabled).toBe(false);
  expect(screen.getByText('审核版本：3')).toBeDefined();
});

test('a stale review body cannot replace a newer credential view after decoding completes', async () => {
  login(); let finish!: (value: unknown) => void;
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return Object.assign(response({}), { json: () => new Promise<unknown>(done => { finish = done; }) });
    return response(page([{ ...row(), rowVersion: new Headers(init?.headers).get('X-Admin-Token') === 'new-admin' ? 9 : 3 }]));
  });
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  await act(async () => { localStorage.setItem('turtle_admin_token', 'new-admin'); window.dispatchEvent(new StorageEvent('storage')); });
  await screen.findByText('审核版本：9');
  await act(async () => finish({ ok: true, feedback: { ...row(), rowVersion: 4, status: 'approved', reviewedAt: '2026-10-09T00:01:00Z' } }));
  expect(screen.getByText('审核版本：9')).toBeDefined(); expect(screen.queryByText('审核版本：4')).toBeNull();
});

test('a stale list body cannot repopulate old private feedback after credential rotation', async () => {
  login(); let finish!: (value: unknown) => void;
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => new Headers(init?.headers).get('X-Admin-Token') === 'synthetic-admin'
    ? Object.assign(response({}), { json: () => new Promise<unknown>(done => { finish = done; }) })
    : response(page([{ ...row(), question: '新口令的反馈', rowVersion: 9 }])));
  render(<AdminFeedbackPage />); await waitFor(() => expect(finish).toBeTypeOf('function'));
  await act(async () => { localStorage.setItem('turtle_admin_token', 'new-admin'); window.dispatchEvent(new StorageEvent('storage')); });
  await screen.findByText('新口令的反馈'); await act(async () => finish(page()));
  expect(screen.queryByText('合成问题一')).toBeNull(); expect(screen.getByText('审核版本：9')).toBeDefined();
});

test('confirmed privacy revocation updates only its matching newer parent row and closing tasks removes private controls', async () => {
  login(); const second = { ...row(), id: otherId, question: '另一条合成问题' };
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => init?.method === 'POST'
    ? response({ ok: true, feedback: { ...row(), rowVersion: 4, safeForModel: false } }) : response(page([row(), second])));
  render(<AdminFeedbackPage />); await screen.findByText('合成问题一');
  fireEvent.click(screen.getByRole('button', { name: '高级：AI 修正规则' }));
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: id } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '合成撤销理由' } });
  fireEvent.click(screen.getByRole('button', { name: '撤销模型许可' })); await screen.findByText('审核版本：4');
  expect(screen.getByText('审核版本：3')).toBeDefined(); expect(screen.getByText('另一条合成问题')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: '收起 AI 修正规则' }));
  expect(screen.queryByLabelText('选择反馈')).toBeNull();
});

test.each(['list', 'review'])('late rejected %s requests cannot restore errors in the new credential view', async mode => {
  login(); let reject!: (reason: Error) => void;
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    const old = new Headers(init?.headers).get('X-Admin-Token') === 'synthetic-admin';
    if (old && (mode === 'list' || init?.method === 'POST')) return new Promise<Response>((_done, fail) => { reject = fail; });
    return Promise.resolve(response(page([{ ...row(), question: old ? '合成问题一' : '新口令的反馈', rowVersion: old ? 3 : 9 }])));
  });
  render(<AdminFeedbackPage />);
  if (mode === 'review') fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await waitFor(() => expect(reject).toBeTypeOf('function'));
  await act(async () => { localStorage.setItem('turtle_admin_token', 'new-admin'); window.dispatchEvent(new StorageEvent('storage')); });
  await screen.findByText('新口令的反馈'); await act(async () => reject(new Error('OLD_PRIVATE_ERROR')));
  expect(screen.queryByText(/网络错误/)).toBeNull(); expect(screen.getByText('审核版本：9')).toBeDefined();
});

test('a malformed review acknowledgement shows a contract error and preserves the current row', async () => {
  login(); vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => init?.method === 'POST'
    ? response({ ok: true, feedback: { ...row(), rowVersion: 5, status: 'approved', reviewedAt: '2026-10-09T00:01:00Z' } }) : response(page()));
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await screen.findByText(/反馈数据暂时无法核验/); expect(screen.getByText('审核版本：3')).toBeDefined();
});
