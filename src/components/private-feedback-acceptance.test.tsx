import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import FeedbackButton from './FeedbackButton';
import { candidateDetail, candidateId } from '../../tests/frontend/agent-review-fixtures';
import { AgentReviewContractError, decodeCandidateDetail } from '@/lib/agent-review-contract';

vi.mock('next/navigation', () => ({ usePathname: () => '/' }));

test('candidate review preserves the player reason as an unverified claim', () => {
  const detail = candidateDetail();
  const input = { ...detail, material: { ...detail.material,
    sanitizedInput: { ...detail.material.sanitizedInput, reason: '合成玩家理由，尚未人审' } } };
  expect(decodeCandidateDetail(input, candidateId).material?.sanitizedInput.reason).toBe('合成玩家理由，尚未人审');
});

test('a well-sized but malformed candidate UUID cannot acquire review authority', () => {
  const detail = candidateDetail();
  detail.candidateId = 'z'.repeat(36);
  expect(() => decodeCandidateDetail(detail, candidateId)).toThrow(AgentReviewContractError);
});

test('a non-Error catalog rejection presents a retryable message', async () => {
  vi.stubGlobal('fetch', () => Promise.reject('synthetic rejection'));
  render(<FeedbackButton />);
  fireEvent.click(screen.getByRole('button'));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', '列表加载失败，请重试');
  expect(screen.getByRole('button', { name: '重试列表' })).toBeDefined();
});

test('submitting an incomplete form cannot send a feedback request', () => {
  const fetch = vi.fn(() => new Promise<Response>(() => {}));
  vi.stubGlobal('fetch', fetch);
  const view = render(<FeedbackButton />);
  fireEvent.click(screen.getByRole('button'));
  fireEvent.submit(view.container.querySelector('form')!);
  expect(fetch).toHaveBeenCalledTimes(1); // The catalog read only.
  expect(screen.queryByText('✅ 提交成功，感谢反馈！')).toBeNull();
});

test('unbound feedback uses the explicit soup selection and never fabricates a turn identity', async () => {
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal('fetch', async (_input: unknown, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push(JSON.parse(String(init.body)));
      return new Response('{}');
    }
    return new Response(JSON.stringify({ soups: [{ id: 'synthetic', title: '合成题目', surface: '合成汤面',
      tags: ['推理'], difficulty: 2, difficultyLimits: { xuermu: 3, baozi: 5, tianyi: 7 } }] }));
  });
  render(<FeedbackButton />);
  fireEvent.click(screen.getByRole('button'));
  await screen.findByRole('option', { name: '合成题目' });
  fireEvent.change(screen.getByRole('combobox', { name: '选择反馈汤品' }), { target: { value: 'synthetic' } });
  fireEvent.change(screen.getByPlaceholderText('例如：故事中只有六个人吗？'), { target: { value: '  合成问题  ' } });
  fireEvent.change(screen.getByText('请选择主持人的回答…').closest('select')!, { target: { value: '不是' } });
  fireEvent.change(screen.getByText('请选择标准答案…').closest('select')!, { target: { value: '是' } });
  fireEvent.click(screen.getByRole('button', { name: '提交反馈' }));
  await screen.findByText('✅ 提交成功，感谢反馈！');
  expect(posts).toEqual([{ soupId: 'synthetic', question: '合成问题', hostAnswer: '不是', expectedAnswer: '是' }]);
});
