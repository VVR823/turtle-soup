import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import FeedbackButton from './FeedbackButton';

vi.mock('next/navigation', () => ({ usePathname: () => '/game/synthetic' }));
const source = { soupId: 'synthetic', soupTitle: '合成题目', turnId: 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa',
  question: '小明是凶手吗？', hostAnswer: '不是' };
test('explicit per-answer form preserves actual turn, prefilled question and host, but no guessed expected answer', async () => {
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    if (init?.method !== 'POST') throw new Error('Bound form must not discover a different catalog or private trace');
    posts.push(JSON.parse(String(init.body))); return new Response(JSON.stringify({ ok: true, id: source.turnId }), { status: 200 });
  });
  render(<FeedbackButton source={source} />);
  fireEvent.click(screen.getByRole('button', { name: '反馈这次回答' }));
  expect((screen.getByPlaceholderText('例如：故事中只有六个人吗？') as HTMLTextAreaElement).value).toBe('小明是凶手吗？');
  expect(screen.getByRole('button', { name: '提交反馈' }).hasAttribute('disabled')).toBe(true);
  const expected = screen.getByText('请选择标准答案…').closest('select')!;
  fireEvent.change(expected, { target: { value: '是' } });
  fireEvent.click(screen.getByRole('button', { name: '提交反馈' }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({ soupId: 'synthetic', turnId: source.turnId, question: '小明是凶手吗？', hostAnswer: '不是', expectedAnswer: '是' });
  expect(posts[0].safeForModel).toBeUndefined(); expect(posts[0].approved).toBeUndefined();
});
