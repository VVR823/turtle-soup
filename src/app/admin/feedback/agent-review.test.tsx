import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import AdminFeedbackPage from './page';
import { runId, reportId } from '../../../../tests/frontend/agent-review-fixtures';

test('existing admin flow exposes manually edited privacy and separate explicit start with verified new CAS', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin'); const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  const item = { id: reportId, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: '合成测试汤',
    question: '他知道吗？', hostAnswer: '不是', expectedAnswer: '是', reason: '原始背景，不应覆盖已提交脱敏草稿', status: 'approved',
    reviewedAt: '2026-10-09T00:00:01Z', mergedAt: null, mergedAnswer: null, rowVersion: 2,
    safeForModel: false, sourceState: 'linked', turnId: runId };
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return new Response(JSON.stringify(url.endsWith('/privacy') ? { ok: true, feedback: { ...item, rowVersion: 3, safeForModel: true } } : { runId }), { status: 200 });
    }
    return new Response(JSON.stringify(url.endsWith('/' + runId)
      ? { id: runId, state: 'queued', rowVersion: 0, modelAttemptsUsed: 0, toolAttemptsUsed: 0, candidateId: null,
        deadlineAt: null, reason: null, steps: [] }
      : { feedbacks: [item], totalInRange: 1, nextCursor: null }), { status: 200 });
  });
  render(<AdminFeedbackPage />); await screen.findByText('他知道吗？');
  fireEvent.click(screen.getByRole('button', { name: '打开任务管理' }));
  fireEvent.change(screen.getByLabelText('选择反馈'), { target: { value: reportId } });
  fireEvent.change(screen.getByLabelText('脱敏后的问题'), { target: { value: '事后他知道吗？' } });
  fireEvent.change(screen.getByLabelText('脱敏后的反馈背景'), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('隐私审核理由'), { target: { value: '逐项人工核对隐私' } });
  fireEvent.click(screen.getByLabelText('已逐项检查隐私与脱敏内容'));
  fireEvent.click(screen.getByRole('button', { name: '保存脱敏授权（不启动任务）' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '显式启动修复任务' }).hasAttribute('disabled')).toBe(false));
  expect(posts).toHaveLength(1); expect(posts[0].body.sanitizedQuestion).toBe('事后他知道吗？');
  expect((screen.getByLabelText('脱敏后的问题') as HTMLTextAreaElement).value).toBe('事后他知道吗？');
  expect((screen.getByLabelText('脱敏后的反馈背景') as HTMLTextAreaElement).value).toBe('');
  expect((screen.getByLabelText('已逐项检查隐私与脱敏内容') as HTMLInputElement).checked).toBe(false);
  expect((screen.getByLabelText('隐私审核理由') as HTMLTextAreaElement).value).toBe('');
  fireEvent.click(screen.getByRole('button', { name: '显式启动修复任务' }));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1].body).toMatchObject({ feedbackId: reportId, expectedFeedbackVersion: 3 });
  expect(Object.keys(posts[1].body).sort()).toEqual(['expectedFeedbackVersion', 'feedbackId', 'requestId']);
});
