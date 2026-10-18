import { expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import AdminFeedbackPage from './page';

const id = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
function row(changes: Record<string, unknown> = {}) {
  return { id, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: 'Test', question: '谁是凶手？',
    hostAnswer: '是', expectedAnswer: '不知道', reason: null, status: 'pending', reviewedAt: null,
    mergedAt: null, mergedAnswer: null, rowVersion: 3, safeForModel: false, sourceState: 'unverified', turnId: null, ...changes };
}
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const page = (feedbacks = [row()], totalInRange = feedbacks.length, nextCursor: string | null = null) => ({ feedbacks, totalInRange, nextCursor });

test('previously approved invalid historical feedback still offers a safe reject action', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  const old = row({ status: 'approved', hostAnswer: ' \t ', reviewedAt: '2026-10-09T00:01:00Z' });
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => init?.method === 'POST'
    ? response({ ok: true, feedback: { ...old, rowVersion: 4, status: 'rejected', reviewedAt: '2026-10-09T00:02:00Z' } })
    : response(page([old])));
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '不采纳' }));
  await screen.findByText('审核版本：4'); expect(screen.queryByRole('button', { name: '不采纳' })).toBeNull();
});

test.each(['soupId', 'question', 'hostAnswer', 'expectedAnswer'])(
  'historical blank %s does not hide normal rows and only allows rejection', async field => {
    localStorage.setItem('turtle_admin_token', 'synthetic-admin'); let rejected: RequestInit | undefined;
    const old = row({ id: 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb', soupTitle: '历史空白反馈', [field]: ' \t ' });
    vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === 'POST') { rejected = init; return response({ ok: true,
        feedback: { ...old, status: 'rejected', rowVersion: 4, reviewedAt: '2026-10-09T00:02:00Z' } }); }
      return response(page([row({ question: '正常反馈仍可审核？' }), old]));
    });
    render(<AdminFeedbackPage />); await screen.findByText('正常反馈仍可审核？');
    const card = (await screen.findByText('历史空白反馈', { selector: 'span' })).closest('div.card')!;
    expect(within(card as HTMLElement).getByText(/必填内容仅空白/)).toBeTruthy();
    expect(within(card as HTMLElement).getByRole('button', { name: '确认反馈有效' }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(within(card as HTMLElement).getByRole('button', { name: '不采纳' }));
    await within(card as HTMLElement).findByText('审核版本：4');
    expect(JSON.parse(String(rejected?.body))).toEqual({ expectedRowVersion: 3 });
    expect(screen.getByText('正常反馈仍可审核？')).toBeTruthy();
  },
);

test('initial invalid response leaves a usable refresh action that retrieves verified rows', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin'); let reads = 0;
  vi.stubGlobal('fetch', async () => response(++reads === 1 ? { feedbacks: 'invalid' } : page()));
  render(<AdminFeedbackPage />); await screen.findByText(/无法核验/);
  const refresh = screen.getByRole('button', { name: '刷新' });
  expect(refresh.hasAttribute('disabled')).toBe(false);
  fireEvent.click(refresh); await screen.findByText('谁是凶手？'); expect(reads).toBe(2);
});

test('review sends actual rowVersion and shows the verified next server version', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin'); let posted: RequestInit | undefined;
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
    if (init?.method === 'POST') { posted = init; return response({ ok: true, feedback: row({ rowVersion: 4,
      status: 'approved', reviewedAt: '2026-10-09T00:01:00Z' }) }); }
    return response(page());
  });
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await screen.findByText('审核版本：4');
  expect(JSON.parse(String(posted?.body))).toEqual({ expectedRowVersion: 3 });
  expect(new Headers(posted?.headers).get('Content-Type')).toBe('application/json');
  expect(screen.queryByRole('button', { name: '确认反馈有效' })).toBeNull();
});

test('stale 409 keeps the current row and asks for refresh instead of local approval', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => init?.method === 'POST'
    ? response({ code: 'feedback_version_conflict', detail: '请刷新后重新核对这条反馈' }, 409) : response(page()));
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await screen.findByText(/请刷新/); expect(screen.getByRole('button', { name: '确认反馈有效' })).toBeTruthy();
  expect(screen.getByText('审核版本：3')).toBeTruthy();
});

test('late old-credential review cannot replace a newer credential row', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-old'); let resolve!: (response: Response) => void;
  const waiting = new Promise<Response>(done => { resolve = done; });
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
    if (init?.method === 'POST') return waiting;
    return response(page([row({ rowVersion: new Headers(init?.headers).get('X-Admin-Token') === 'synthetic-new' ? 9 : 3 })]));
  });
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await act(async () => { localStorage.setItem('turtle_admin_token', 'synthetic-new'); window.dispatchEvent(new StorageEvent('storage')); });
  await screen.findByText('审核版本：9');
  await act(async () => { resolve(response({ ok: true, feedback: row({ rowVersion: 4, status: 'approved', reviewedAt: '2026-10-09T00:01:00Z' }) })); });
  expect(screen.getByText('审核版本：9')).toBeTruthy(); expect(screen.getByRole('button', { name: '确认反馈有效' })).toBeTruthy();
});

test('load more uses a bounded server cursor and labels only this time window count', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin'); const requested: string[] = [];
  vi.stubGlobal('fetch', async (input: string | URL | Request) => {
    const url = String(input); requested.push(url);
    return response(url.includes('cursor=owned_cursor') ? page([row({ id: 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb', question: '第二条问题？' })], 2)
      : page([row()], 2, 'owned_cursor'));
  });
  render(<AdminFeedbackPage />); await screen.findByText('谁是凶手？');
  fireEvent.click(await screen.findByRole('button', { name: '加载更多' })); await screen.findByText('第二条问题？');
  expect(screen.getByText(/最近7天.*2.*已加载.*2/)).toBeTruthy();
  expect(requested.some(url => url.includes('cursor=owned_cursor'))).toBe(true);
});

test('a plain ok response does not manufacture review success or browser time', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => init?.method === 'POST' ? response({ ok: true }) : response(page()));
  render(<AdminFeedbackPage />); fireEvent.click(await screen.findByRole('button', { name: '确认反馈有效' }));
  await screen.findByText(/无法核验/); expect(screen.getByText('审核版本：3')).toBeTruthy();
  expect(screen.getByRole('button', { name: '确认反馈有效' })).toBeTruthy();
});
