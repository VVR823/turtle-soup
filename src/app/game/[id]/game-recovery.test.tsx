import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import GamePage from './page';
import { getLastSession, saveLastSession } from '@/lib/api';
import { readPending, writePending } from '@/lib/game-journal';

const navigation = vi.hoisted(() => ({ id: 'synthetic', level: 'xuermu', push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: navigation.push }),
  useParams: () => ({ id: navigation.id }), useSearchParams: () => new URLSearchParams({ level: navigation.level }) }));
const target = { soupId: 'synthetic', level: 'xuermu' };
const evaluation = { completion: 50, verifiedCoverage: 50, scoreVersion: 'coverage-v1', reconstructionScore: null,
  plotProgress: 80, evaluation: '合成评分', keyPointsCovered: ['A'], keyPointsMissing: ['B'], bottom: '合成汤底' };
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }); }
function saved(changed = {}) { return { ...target, sessionId: 'owned', soupTitle: '合成标题', soupSurface: '合成汤面',
  questionLimit: 3, questionsAsked: 0, remaining: 3, unlocks: null, status: 'playing', messages: [], evaluation: null, ...changed }; }
function created(requestId: string, changed = {}) { return { requestId, sessionId: 'owned', soupTitle: '合成标题',
  soupSurface: '合成汤面', questionLimit: 3, unlocks: null, ...changed }; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
beforeEach(() => {
  navigation.id = 'synthetic'; navigation.level = 'xuermu';
  vi.stubGlobal('alert', vi.fn()); vi.stubGlobal('confirm', vi.fn(() => false));
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: () => {} });
});
afterEach(() => {
  if (originalScroll) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScroll);
  else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});

test('paused original game preserves history and request UUID while disabling both controls', async () => {
  const operation = { ...target, kind: 'ask' as const, sessionId: 'owned', question: '原始问题吗？',
    requestId: 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa' };
  saveLastSession({ ...target, sessionId: 'owned' }); writePending(operation); let posts = 0;
  vi.stubGlobal('fetch', async (input: string | URL | Request, init?: RequestInit) => {
    if (init?.method === 'POST') posts++;
    return String(input).includes('/turns/') ? json({}, 404) : json(saved({ ruleSuspended: true,
      messages: [{ role: 'user', content: '原历史问题', timestamp: 1 }, { role: 'host', content: '是', timestamp: 2 }] }));
  });
  render(<GamePage />); await screen.findByText(/此版本规则已暂停/); await screen.findByText('原历史问题');
  expect((screen.getByRole('textbox', { name: '向主持人提问' }) as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: /揭晓答案/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(readPending(target)).toEqual(operation); expect(getLastSession()?.sessionId).toBe('owned'); expect(posts).toBe(0);
});

test('paused ended game still displays its frozen evaluation', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  vi.stubGlobal('fetch', async () => json(saved({ ruleSuspended: true, status: 'given_up', evaluation })));
  render(<GamePage />); await screen.findByText('合成汤底'); await screen.findByText(/此版本规则已暂停/);
  // Ended games already remove the input rather than render a disabled one.
  expect(screen.queryByRole('textbox', { name: '向主持人提问' })).toBeNull();
  expect((screen.getByRole('button', { name: /揭晓答案/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(getLastSession()?.sessionId).toBe('owned');
});

test('question and reveal are disabled until a verified creation returns', async () => {
  const slow = deferred<Response>(); let id = '';
  const fetch = vi.fn((_input: string | URL | Request, init?: RequestInit) => { id = JSON.parse(String(init?.body)).requestId; return slow.promise; });
  vi.stubGlobal('fetch', fetch); render(<GamePage />);
  expect((screen.getByRole('textbox', { name: '向主持人提问' }) as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: /揭晓答案/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(readPending(target)).toMatchObject({ kind: 'create', requestId: id });
  await act(async () => { slow.resolve(json(created(id))); });
  expect((screen.getByRole('textbox', { name: '向主持人提问' }) as HTMLInputElement).disabled).toBe(false);
});

test('restore503 exposes manual sync and preserves saved game without a new creation', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); let reads = 0;
  const fetch = vi.fn<(input: string | URL | Request, init?: RequestInit) => Promise<Response>>(async () => reads++ === 0 ? json({}, 503) : json(saved())); vi.stubGlobal('fetch', fetch);
  render(<GamePage />);
  await screen.findByRole('button', { name: '同步原对局' });
  expect(getLastSession()?.sessionId).toBe('owned'); expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: '同步原对局' })); await screen.findByText('合成汤面');
  expect(fetch.mock.calls.every(args => !args[1] || args[1].method !== 'POST')).toBe(true);
});

test('missing creation count keeps both controls disabled and the original creation intent durable', async () => {
  let id = '';
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
    id = JSON.parse(String(init?.body)).requestId;
    const missing = created(id) as Record<string, unknown>; delete missing.questionLimit;
    return json(missing);
  });
  render(<GamePage />); await screen.findByRole('button', { name: '同步原对局' });
  expect((screen.getByRole('textbox', { name: '向主持人提问' }) as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: /揭晓答案/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(readPending(target)).toMatchObject({ kind: 'create', requestId: id });
  expect(getLastSession()).toBeNull();
});

test('ended restore displays frozen evaluation and navigating home does not clear pointer', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  vi.stubGlobal('fetch', async () => json(saved({ status: 'given_up', evaluation })));
  render(<GamePage />); await screen.findByText('合成汤底');
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('50');
  fireEvent.click(screen.getAllByRole('button', { name: '返回大厅' })[0]);
  expect(getLastSession()?.sessionId).toBe('owned');
});

test('StrictMode setup-cleanup-setup sends the persisted creation identity and not a new intent', async () => {
  const ids: string[] = [];
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
    const id = JSON.parse(String(init?.body)).requestId; ids.push(id); return json(created(id));
  });
  render(<StrictMode><GamePage /></StrictMode>); await screen.findByText('合成汤面');
  expect(ids.length).toBeGreaterThanOrEqual(1); expect(new Set(ids).size).toBe(1);
  expect(ids[0]).toMatch(/^[0-9a-f-]{36}$/); expect(readPending(target)).toBeNull();
});

test('changing soup retires a late creation response and its persistent write', async () => {
  const old = deferred<Response>(); let oldId = '';
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body));
    if (body.soupId === 'synthetic') { oldId = body.requestId; return old.promise; }
    return json(created(body.requestId, { sessionId: 'new-owned', soupTitle: '新汤标题', soupSurface: '新汤面' }));
  });
  const page = render(<GamePage />); navigation.id = 'other'; page.rerender(<GamePage />);
  await screen.findByText('新汤面');
  await act(async () => { old.resolve(json(created(oldId, { soupTitle: '过时标题', soupSurface: '过时汤面' }))); });
  expect(screen.queryByText('过时标题')).toBeNull(); expect(getLastSession()?.sessionId).toBe('new-owned');
  expect(readPending(target)?.kind).toBe('create');
});

test('lost question response refresh recovers the original UUID once without claiming uncharged or re-posting', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); let id = ''; let committed = false; let posts = 0;
  vi.stubGlobal('fetch', async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST') { posts++; id = JSON.parse(String(init.body)).requestId; committed = true; throw new TypeError('合成丢响应'); }
    if (url.includes('/turns/')) { expect(url.endsWith(`/turns/${id}`)).toBe(true); return json({ sessionId: 'owned', requestId: id,
      turnId: 'turn-owned', state: 'completed', kind: 'answer', reply: '是', remaining: 2, isFreeReminder: false,
      isWin: false, isReveal: false, isGiveup: false, limitReached: false }); }
    return json(saved(committed ? { questionsAsked: 1, remaining: 2, messages: [
      { role: 'user', content: '合成问题吗', timestamp: 1, turnId: 'turn-owned', isFreeReminder: false },
      { role: 'host', content: '是', timestamp: 2, turnId: 'turn-owned', isFreeReminder: false }] } : {}));
  });
  const first = render(<GamePage />); await screen.findByText('合成汤面');
  fireEvent.change(screen.getByRole('textbox', { name: '向主持人提问' }), { target: { value: '合成问题吗' } });
  fireEvent.click(screen.getByRole('button', { name: '发送' })); await screen.findByRole('button', { name: '同步原对局' });
  expect(document.body.textContent).not.toContain('不会扣次数'); expect(readPending(target)).toMatchObject({ requestId: id });
  first.unmount(); render(<GamePage />); await screen.findByText('是');
  expect(screen.getAllByText('合成问题吗')).toHaveLength(1); expect(screen.getByText('2/3')).toBeDefined();
  expect(posts).toBe(1); expect(readPending(target)).toBeNull();
});

test('ordinary retry cannot discard an uncertain request and cancelling explicit restart preserves it', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); let posts = 0;
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
    if (init?.method === 'POST') { posts++; throw new TypeError('合成丢响应'); } return json(saved());
  });
  render(<GamePage />); await screen.findByText('合成汤面');
  fireEvent.change(screen.getByRole('textbox', { name: '向主持人提问' }), { target: { value: '合成问题吗' } });
  fireEvent.click(screen.getByRole('button', { name: '发送' })); await screen.findByRole('button', { name: '同步原对局' });
  const pending = readPending(target); fireEvent.click(screen.getByRole('button', { name: '放弃待同步请求并另开' }));
  expect(readPending(target)).toEqual(pending); expect(posts).toBe(1);
});

test('review badges use public free metadata rather than emoji guesses', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  vi.stubGlobal('fetch', async () => json(saved({ questionsAsked: 1, remaining: 2, messages: [
    { role: 'user', content: '收费问题', timestamp: 1, isFreeReminder: false }, { role: 'host', content: '🤔 是', timestamp: 2, isFreeReminder: false },
    { role: 'user', content: '免费提醒', timestamp: 3, isFreeReminder: true }, { role: 'host', content: '请问是非问题', timestamp: 4, isFreeReminder: true }] })));
  render(<GamePage />); await screen.findByText('合成汤面'); fireEvent.click(screen.getByRole('button', { name: /复个小盘/ }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('免费提醒').closest('.panel')?.textContent).toContain('未计入次数');
  expect(within(dialog).getByText('收费问题').closest('.panel')?.textContent).not.toContain('未计入次数');
});
