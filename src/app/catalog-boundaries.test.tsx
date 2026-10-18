import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import Home from './page';
import DifficultyPage from './difficulty/[id]/page';
import { addPlayedSoup } from '@/lib/api';

const route = vi.hoisted(() => ({ id: 'synthetic', push: vi.fn() }));
vi.mock('next/navigation', () => ({ useParams: () => ({ id: route.id }), useRouter: () => ({ push: route.push }) }));
beforeEach(() => { route.id = 'synthetic'; vi.stubGlobal('scrollTo', vi.fn()); });
const soup = { id: 'synthetic', title: '合成题目', surface: '合成汤面', tags: ['推理'], difficulty: 2,
  difficultyLimits: { xuermu: 3, baozi: 5, tianyi: 7 } };
const response = (soups: unknown[]) => new Response(JSON.stringify({ soups }));
const catalog = () => Array.from({ length: 13 }, (_, i) => ({ ...soup, id: `synthetic-${i}`, title: `目录-${i}` }));

test('an authorized hidden card preserves played status, unknown tags and a bounded surface preview', async () => {
  addPlayedSoup('synthetic');
  vi.stubGlobal('fetch', async () => response([{ ...soup, hidden: true, surface: '汤'.repeat(51), tags: ['合成新标签'] }]));
  render(<Home />); await screen.findByText('合成题目');
  expect(screen.getByText('隐藏彩蛋')).toBeDefined(); expect(screen.getByText('✓ 已玩过')).toBeDefined();
  expect(screen.getByText('合成新标签')).toBeDefined(); expect(screen.getByText('汤'.repeat(50) + '…')).toBeDefined();
  expect(screen.getByRole('link', { name: /合成题目/ }).getAttribute('href')).toBe('/difficulty/synthetic');
});

test.each([{ input: '99', expected: '目录-12' }, { input: '-2', expected: '目录-0' }, { input: '2', expected: '目录-6' }])(
  'pagination clamps an explicit jump $input to a valid page', async ({ input, expected }) => {
    vi.stubGlobal('fetch', async () => response(catalog())); render(<Home />); await screen.findByText('目录-0');
    fireEvent.change(screen.getByRole('spinbutton', { name: '输入页码' }), { target: { value: input } });
    fireEvent.keyDown(screen.getByRole('spinbutton', { name: '输入页码' }), { key: 'Enter' });
    await screen.findByText(expected);
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
  },
);

test('blank page input and a non-Enter key do not navigate; previous-page returns the original cards', async () => {
  vi.stubGlobal('fetch', async () => response(catalog())); render(<Home />); await screen.findByText('目录-0');
  fireEvent.change(screen.getByRole('spinbutton', { name: '输入页码' }), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: '跳转' })); expect(window.scrollTo).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('spinbutton', { name: '输入页码' }), { target: { value: '2' } });
  fireEvent.keyDown(screen.getByRole('spinbutton', { name: '输入页码' }), { key: 'ArrowRight' });
  expect(screen.queryByText('目录-6')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '下一页' })); await screen.findByText('目录-6');
  fireEvent.click(screen.getByRole('button', { name: '上一页' })); await screen.findByText('目录-0');
});

test('empty search results differ from an empty catalog and clearing search restores the list', async () => {
  vi.stubGlobal('fetch', async (input: string) => String(input).includes('q=') ? response([]) : response([soup]));
  render(<Home />); await screen.findByText('合成题目');
  fireEvent.change(screen.getByRole('textbox', { name: '搜索海龟汤' }), { target: { value: 'missing' } });
  await screen.findByText('没有找到与「missing」相关的海龟汤');
  expect(screen.queryByText('暂时没有海龟汤哦~')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '清除搜索' })); await screen.findByText('合成题目');
});

test('nonempty search reports its complete returned count', async () => {
  vi.stubGlobal('fetch', async () => response([soup])); render(<Home />); await screen.findByText('合成题目');
  fireEvent.change(screen.getByRole('textbox', { name: '搜索海龟汤' }), { target: { value: 'synthetic' } });
  await screen.findByText('找到 1 道与「synthetic」相关的海龟汤');
});

test('a non-Error catalog failure remains retryable and explicit retry restores the list', async () => {
  const fetch = vi.fn().mockRejectedValueOnce('synthetic failure').mockImplementation(async () => response([soup]));
  vi.stubGlobal('fetch', fetch); render(<Home />);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', '列表加载失败，请重试');
  fireEvent.click(screen.getByRole('button', { name: '重试列表' })); await screen.findByText('合成题目');
  expect(fetch).toHaveBeenCalledTimes(2);
});

test('a late rejected old search cannot replace the current successful catalog with an error', async () => {
  let reject!: (reason: Error) => void; let reads = 0;
  vi.stubGlobal('fetch', () => ++reads === 1 ? new Promise<Response>((_done, fail) => { reject = fail; }) : Promise.resolve(response([soup])));
  render(<Home />); await waitFor(() => expect(reads).toBe(1));
  fireEvent.change(screen.getByRole('textbox', { name: '搜索海龟汤' }), { target: { value: 'new' } });
  await screen.findByText('合成题目'); await act(async () => reject(new Error('OLD_PRIVATE_ERROR')));
  expect(screen.queryByRole('alert')).toBeNull(); expect(screen.getByText('合成题目')).toBeDefined();
});

test.each(['keyboard', 'backdrop', 'button'])('the catalog modal retains inner interaction and closes by %s', mode => {
  render(<Home />); fireEvent.click(screen.getByRole('button', { name: '请作者喝杯奶茶' }));
  const dialog = screen.getByRole('dialog');
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭赞赏框' }));
  fireEvent.click(within(dialog).getByRole('img')); fireEvent.keyDown(window, { key: 'Enter' });
  expect(screen.getByRole('dialog')).toBeDefined();
  if (mode === 'keyboard') fireEvent.keyDown(window, { key: 'Escape' });
  else if (mode === 'backdrop') fireEvent.click(dialog);
  else fireEvent.click(within(dialog).getByRole('button', { name: '关闭' }));
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('difficulty selection uses the selected public identity and exact difficulty key', async () => {
  vi.stubGlobal('fetch', async () => response([soup])); render(<DifficultyPage />); await screen.findByText('合成题目');
  for (const [name, level] of [['许二木', 'xuermu'], ['包子', 'baozi'], ['天一', 'tianyi']]) {
    fireEvent.click(screen.getByRole('button', { name: new RegExp(name) }));
    expect(route.push).toHaveBeenLastCalledWith(`/game/synthetic?level=${level}`);
  }
  fireEvent.click(screen.getByRole('button', { name: '返回大厅' }));
  expect(route.push).toHaveBeenLastCalledWith('/');
});

test('a valid directory without the requested soup exposes missing state and a safe route home', async () => {
  vi.stubGlobal('fetch', async () => response([])); render(<DifficultyPage />);
  await screen.findByText('没有找到这道汤哦~');
  fireEvent.click(screen.getAllByRole('button', { name: '返回大厅' })[1]);
  expect(route.push).toHaveBeenLastCalledWith('/');
});

test('difficulty non-Error failure can recover through its explicit retry', async () => {
  const fetch = vi.fn().mockRejectedValueOnce('synthetic failure').mockImplementation(async () => response([soup]));
  vi.stubGlobal('fetch', fetch); render(<DifficultyPage />); await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: '重试列表' })); await screen.findByText('合成题目');
  expect(screen.queryByRole('alert')).toBeNull();
});
