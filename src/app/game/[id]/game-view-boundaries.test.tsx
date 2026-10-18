import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import GamePage from './page';
import { getLastSession, saveLastSession } from '@/lib/api';
import { readPending } from '@/lib/game-journal';
import type { SessionSnapshot } from '@/lib/game-contract';

const navigation = vi.hoisted(() => ({ id: 'synthetic', level: 'xuermu', push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: navigation.push }), usePathname: () => '/game/synthetic', useParams: () => ({ id: navigation.id }),
  useSearchParams: () => new URLSearchParams(navigation.level ? { level: navigation.level } : {}) }));
const target = { soupId: 'synthetic', level: 'xuermu' };
const legacyEvaluation = { completion: 50, evaluation: '合成历史评语', keyPointsCovered: ['历史涉及事实'],
  keyPointsMissing: ['历史未涉及事实'], bottom: '合成历史汤底' };
const saved = (change: Partial<SessionSnapshot> = {}): SessionSnapshot => ({ sessionId: 'owned', soupId: 'synthetic',
  soupTitle: '合成标题', soupSurface: '合成汤面', questionLimit: 3, questionsAsked: 0, remaining: 3, unlocks: null,
  status: 'playing', messages: [], evaluation: null, ...change });
const json = (value: unknown, status = 200, headers?: HeadersInit) => new Response(JSON.stringify(value), { status, headers });
const scroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
beforeEach(() => {
  navigation.id = 'synthetic'; navigation.level = 'xuermu';
  vi.stubGlobal('confirm', vi.fn(() => false)); vi.stubGlobal('alert', vi.fn());
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: () => {} });
});
afterEach(() => { if (scroll) Object.defineProperty(Element.prototype, 'scrollIntoView', scroll); else Reflect.deleteProperty(Element.prototype, 'scrollIntoView'); });
function restore(change: Partial<SessionSnapshot> = {}) {
  saveLastSession({ ...target, sessionId: 'owned' });
  vi.stubGlobal('fetch', async () => json(saved(change)));
  return render(<GamePage />);
}

test('unlimited sessions display unlimited controls without an invented numeric budget', async () => {
  restore({ questionLimit: null, remaining: null }); await screen.findByText('合成汤面');
  expect(screen.getByText('不限次')).toBeDefined(); expect(screen.getByText('不限次数')).toBeDefined();
  expect(screen.getByRole('button', { name: '我认输 / 揭晓汤底' })).toBeDefined();
  expect(screen.queryByText(/null\/null/)).toBeNull();
});

test('a verified larger remaining budget is displayed as returned', async () => {
  restore({ questionLimit: 10, remaining: 10 }); await screen.findByText('10/10');
  expect(screen.getByText('10/10').className).toContain('text-accent-text');
});

test.each(['keyboard', 'backdrop', 'header', 'footer'])('review modal preserves inner interaction and closes via %s', async method => {
  restore(); await screen.findByText('合成汤面');
  fireEvent.click(screen.getByRole('button', { name: /复个小盘/ }));
  const dialog = screen.getByRole('dialog');
  expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: '关闭复盘' }));
  expect(within(dialog).getByText('还没有任何提问，先去问问主持人吧~')).toBeDefined();
  fireEvent.click(within(dialog).getByRole('heading', { name: '复个小盘' })); fireEvent.keyDown(window, { key: 'Enter' });
  expect(screen.getByRole('dialog')).toBeDefined();
  if (method === 'keyboard') fireEvent.keyDown(window, { key: 'Escape' });
  else if (method === 'backdrop') fireEvent.click(dialog);
  else fireEvent.click(within(dialog).getByRole('button', { name: method === 'header' ? '关闭复盘' : '继续推理' }));
  expect(screen.queryByRole('dialog')).toBeNull();
});

test.each(['missing', 'next-user'])('an unpaired historical question shows waiting rather than guessing the %s reply', async kind => {
  const messages: SessionSnapshot['messages'] = [{ role: 'user', content: '尚未配对的历史问题', timestamp: 1 }];
  if (kind === 'next-user') messages.push({ role: 'user', content: '第二个历史问题', timestamp: 2 }, { role: 'host', content: '是', timestamp: 3 });
  restore({ messages }); await screen.findByText('合成汤面'); fireEvent.click(screen.getByRole('button', { name: /复个小盘/ }));
  expect(within(screen.getByRole('dialog')).getByText('（等待主持人回复…）')).toBeDefined();
});

test('feedback is offered only for the bound completed public question/answer pair', async () => {
  const turnId = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
  restore({ questionsAsked: 1, remaining: 2, messages: [{ role: 'user', content: '合成问题', timestamp: 1, turnId },
    { role: 'host', content: '不是', timestamp: 2, turnId }] });
  await screen.findByText('合成汤面'); fireEvent.click(screen.getByRole('button', { name: '反馈这次回答' }));
  expect((screen.getByPlaceholderText('例如：故事中只有六个人吗？') as HTMLTextAreaElement).value).toBe('合成问题');
  expect(screen.getByRole('combobox', { name: '选择反馈汤品' }).hasAttribute('disabled')).toBe(true);
});

test('an ended legacy evaluation labels covered and missing facts as historical', async () => {
  restore({ status: 'given_up', evaluation: legacyEvaluation }); await screen.findByText('合成历史汤底');
  expect(screen.getByText('旧记录中的已触及要点')).toBeDefined(); expect(screen.getByText('旧记录中的未触及要点')).toBeDefined();
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('50');
});

test('header navigation preserves the current route identity without mutating the saved session', async () => {
  restore(); await screen.findByText('合成汤面');
  fireEvent.click(screen.getByRole('button', { name: '选择难度' })); expect(navigation.push).toHaveBeenLastCalledWith('/difficulty/synthetic');
  fireEvent.click(screen.getByRole('button', { name: '返回大厅' })); expect(navigation.push).toHaveBeenLastCalledWith('/');
  expect(getLastSession()).toEqual({ ...target, sessionId: 'owned' });
});

test('the ended-result route home is separate from starting another game', async () => {
  restore({ status: 'given_up', evaluation: legacyEvaluation }); await screen.findByText('合成历史汤底');
  fireEvent.click(screen.getAllByRole('button', { name: '返回大厅' }).at(-1)!);
  expect(navigation.push).toHaveBeenLastCalledWith('/'); expect(getLastSession()?.sessionId).toBe('owned');
});

test('a rate-limited restore exposes Retry-After and cannot retry ahead of the deadline', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  const fetch = vi.fn(async () => json({}, 429, { 'Retry-After': '9' })); vi.stubGlobal('fetch', fetch);
  render(<GamePage />); await screen.findByText('请等待 9 秒后再同步。');
  fireEvent.click(screen.getByRole('button', { name: '同步原对局' }));
  expect(fetch).toHaveBeenCalledTimes(1); expect(getLastSession()?.sessionId).toBe('owned');
});

test('authentication failure exposes explicit revalidation and preserves the saved game', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); vi.stubGlobal('fetch', async () => json({}, 401));
  render(<GamePage />); await screen.findByRole('button', { name: '重新验证口令' });
  expect(getLastSession()?.sessionId).toBe('owned'); expect(screen.queryByText('合成汤面')).toBeNull();
});

test('checking a lifted rule suspension restores the original game without a creation POST', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); let reads = 0;
  const fetch = vi.fn(async () => json(saved({ ruleSuspended: ++reads === 1 }))); vi.stubGlobal('fetch', fetch);
  render(<GamePage />); fireEvent.click(await screen.findByRole('button', { name: '检查暂停是否解除' }));
  await screen.findByText('合成汤面');
  expect(screen.queryByText(/此版本规则已暂停/)).toBeNull();
  expect((screen.getByRole('textbox', { name: '向主持人提问' }) as HTMLInputElement).disabled).toBe(false);
  expect(fetch).toHaveBeenCalledTimes(2); expect(getLastSession()?.sessionId).toBe('owned');
});

test('submitting while initialization is pending or with only whitespace never sends a question', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); let finish!: (value: Response) => void;
  const fetch = vi.fn(() => new Promise<Response>(done => { finish = done; })); vi.stubGlobal('fetch', fetch);
  const view = render(<GamePage />); fireEvent.submit(view.container.querySelector('form')!);
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => finish(json(saved())));
  fireEvent.change(screen.getByRole('textbox', { name: '向主持人提问' }), { target: { value: '   ' } });
  fireEvent.submit(view.container.querySelector('form')!); expect(fetch).toHaveBeenCalledTimes(1);
});

test('explicit abandonment confirmation creates a new request and changes only the verified saved pointer', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); const posted: Record<string, unknown>[] = [];
  vi.stubGlobal('confirm', vi.fn(() => true));
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    if (init?.method !== 'POST') return json(saved());
    const body = JSON.parse(String(init.body)); posted.push(body);
    if (body.question) throw new TypeError('synthetic lost reply');
    return json({ requestId: body.requestId, sessionId: 'new-owned', soupTitle: '新合成标题', soupSurface: '新合成汤面', questionLimit: 3, unlocks: null });
  });
  render(<GamePage />); await screen.findByText('合成汤面');
  fireEvent.change(screen.getByRole('textbox', { name: '向主持人提问' }), { target: { value: '合成问题' } });
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  fireEvent.click(await screen.findByRole('button', { name: '放弃待同步请求并另开' })); await screen.findByText('新合成汤面');
  expect(window.confirm).toHaveBeenCalledTimes(1); expect(posted).toHaveLength(2);
  expect(posted[1].requestId).not.toBe(posted[0].requestId); expect(posted[1].question).toBeUndefined();
  expect(getLastSession()?.sessionId).toBe('new-owned'); expect(readPending(target)).toBeNull();
});

test('an ended game can explicitly create a fresh game without an abandonment prompt', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    if (init?.method !== 'POST') return json(saved({ status: 'given_up', evaluation: legacyEvaluation }));
    const body = JSON.parse(String(init.body));
    return json({ requestId: body.requestId, sessionId: 'new-owned', soupTitle: '新合成标题', soupSurface: '新合成汤面', questionLimit: 3, unlocks: null });
  });
  render(<GamePage />); await screen.findByText('合成历史汤底'); fireEvent.click(screen.getByRole('button', { name: '再来一局' }));
  await screen.findByText('新合成汤面'); expect(window.confirm).not.toHaveBeenCalled(); expect(screen.queryByText('合成历史汤底')).toBeNull();
});

test('failed automatic reveal of an exhausted game keeps its journal and cannot enable a new question', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); const posts: unknown[] = [];
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { posts.push(JSON.parse(String(init.body))); return json({}, 503); }
    return json(saved({ questionsAsked: 3, remaining: 0 }));
  });
  render(<GamePage />); await screen.findByRole('button', { name: '同步原对局' });
  expect(screen.queryByRole('textbox', { name: '向主持人提问' })).toBeNull();
  expect(posts).toEqual([{ sessionId: 'owned' }]); expect(readPending(target)).toMatchObject({ kind: 'reveal', sessionId: 'owned' });
});

test('missing route values cannot send a creation or produce a playable guessed session', async () => {
  navigation.id = ''; navigation.level = '';
  const fetch = vi.fn(async () => json({}, 400)); vi.stubGlobal('fetch', fetch);
  render(<GamePage />); await screen.findByRole('button', { name: '同步原对局' });
  expect(fetch).not.toHaveBeenCalled(); expect(getLastSession()).toBeNull();
  expect((screen.getByRole('textbox', { name: '向主持人提问' }) as HTMLInputElement).disabled).toBe(true);
});
