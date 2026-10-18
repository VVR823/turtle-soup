import { beforeEach, expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Home from './page';
import DifficultyPage from './difficulty/[id]/page';
import FeedbackButton from '@/components/FeedbackButton';
import { addUnlockedSoup } from '@/lib/api';

const route = vi.hoisted(() => ({ id: 'synthetic' }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }), useParams: () => ({ id: route.id }), usePathname: () => '/' }));
beforeEach(() => { route.id = 'synthetic'; });
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }); }
const soup = { id: 'synthetic', title: '新目录标题', surface: '合成汤面', tags: ['推理'], difficulty: 2, difficultyLimits: { xuermu: 3, baozi: 5, tianyi: 7 } };
test('difficulty route change hides the previous soup and its action while loading the new route', async () => {
  let resolve!: (response: Response) => void; let reads = 0;
  const slow = new Promise<Response>(done => { resolve = done; });
  vi.stubGlobal('fetch', async () => reads++ === 0 ? json({ soups: [soup] }) : slow);
  const view = render(<DifficultyPage />); await screen.findByText('新目录标题');
  route.id = 'next-synthetic'; view.rerender(<DifficultyPage />);
  expect(screen.queryByText('新目录标题')).toBeNull();
  expect(screen.queryByRole('button', { name: /许二木/ })).toBeNull();
  await act(async () => resolve(json({ soups: [{ ...soup, id: route.id, title: '新目标汤' }] })));
  await screen.findByText('新目标汤');
});
test('late old difficulty response never replaces the new route', async () => {
  let resolve!: (response: Response) => void; let reads = 0;
  const slow = new Promise<Response>(done => { resolve = done; });
  vi.stubGlobal('fetch', async () => reads++ === 0 ? slow : json({ soups: [{ ...soup, id: 'next-synthetic', title: '新目标汤' }] }));
  const view = render(<DifficultyPage />); await waitFor(() => expect(reads).toBe(1));
  route.id = 'next-synthetic'; view.rerender(<DifficultyPage />); await screen.findByText('新目标汤');
  await act(async () => resolve(json({ soups: [soup] })));
  expect(screen.queryByText('新目录标题')).toBeNull(); expect(screen.getByText('新目标汤')).toBeDefined();
});
test('pagination page change resets its draft to the actual new page', async () => {
  vi.stubGlobal('scrollTo', vi.fn());
  vi.stubGlobal('fetch', async () => json({ soups: Array.from({ length: 7 }, (_, index) => ({ ...soup, id: `synthetic-${index}`, title: `目录-${index}` })) }));
  render(<Home />); await screen.findByText('目录-0');
  fireEvent.change(screen.getByRole('spinbutton', { name: '输入页码' }), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: '下一页' })); await screen.findByText('目录-6');
  expect((screen.getByRole('spinbutton', { name: '输入页码' }) as HTMLInputElement).value).toBe('2');
});
test.each([Home, DifficultyPage])('catalog HTTP503 is a retryable error, not an empty directory or missing soup', async Page => {
  vi.stubGlobal('fetch', async () => json({ soups: [] }, 503)); render(<Page />);
  await screen.findByRole('button', { name: '重试列表' }); expect(screen.getByRole('alert')).toBeDefined();
  expect(screen.queryByText('暂时没有海龟汤哦~')).toBeNull(); expect(screen.queryByText('这道汤不见了…')).toBeNull();
});
test('home valid empty directory is displayed only after successful validation', async () => {
  vi.stubGlobal('fetch', async () => json({ soups: [] })); render(<Home />); await screen.findByText('暂时没有海龟汤哦~');
  expect(screen.queryByRole('alert')).toBeNull();
});
test('malformed home directory exposes retry rather than claiming empty', async () => {
  vi.stubGlobal('fetch', async () => json({ soups: {} })); render(<Home />); await screen.findByRole('button', { name: '重试列表' });
  expect(screen.queryByText('暂时没有海龟汤哦~')).toBeNull();
});
test('a late old search response cannot replace the current catalog', async () => {
  let resolve!: (response: Response) => void; const slow = new Promise<Response>(done => { resolve = done; }); let started = false;
  vi.stubGlobal('fetch', async (input: string | URL | Request) => {
    if (!new URL(String(input)).searchParams.get('q')) { started = true; return slow; } return json({ soups: [soup] });
  });
  render(<Home />); await waitFor(() => expect(started).toBe(true));
  fireEvent.change(screen.getByRole('textbox', { name: '搜索海龟汤' }), { target: { value: 'new' } }); await screen.findByText('新目录标题');
  await act(async () => { resolve(json({ soups: [{ ...soup, title: '过时目录标题' }] })); });
  expect(screen.getByText('新目录标题')).toBeDefined(); expect(screen.queryByText('过时目录标题')).toBeNull();
});
test('feedback catalog includes server-approved unlocked soup choices', async () => {
  addUnlockedSoup('synthetic-egg');
  vi.stubGlobal('fetch', async (input: string | URL | Request) => new URL(String(input)).searchParams.get('unlocked') === 'synthetic-egg'
    ? json({ soups: [{ ...soup, id: 'synthetic-egg', title: '隐藏汤反馈', hidden: true }] }) : json({ soups: [] }));
  render(<FeedbackButton />); fireEvent.click(screen.getByRole('button', { name: '主持人答错了？点此提交反馈' }));
  await screen.findByRole('option', { name: '隐藏汤反馈' });
});
test('feedback directory failure can retry and does not enable submission', async () => {
  let reads = 0; vi.stubGlobal('fetch', async () => reads++ === 0 ? json({}, 503) : json({ soups: [soup] }));
  render(<FeedbackButton />); fireEvent.click(screen.getByRole('button', { name: '主持人答错了？点此提交反馈' }));
  await screen.findByRole('button', { name: '重试列表' }); expect((screen.getByRole('button', { name: '提交反馈' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '重试列表' })); await screen.findByRole('option', { name: '新目录标题' });
});
