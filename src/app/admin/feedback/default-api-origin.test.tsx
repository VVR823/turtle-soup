import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { metricsPage } from '../../../../tests/frontend/metrics-fixtures';

test.each([undefined, ''])('admin feedback and metrics share the documented API origin when configured as %s', async origin => {
  vi.resetModules(); vi.stubEnv('NEXT_PUBLIC_API_BASE', origin);
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  const urls: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => {
    urls.push(url);
    return new Response(JSON.stringify(url.includes('/api/metrics/admin') ? metricsPage() : { feedbacks: [], totalInRange: 0, nextCursor: null }));
  });
  const { default: AdminFeedbackPage } = await import('./page');
  render(<AdminFeedbackPage />); await screen.findByText('还没有玩家提交反馈。');
  fireEvent.click(screen.getByRole('button', { name: '查询统计' })); await screen.findByText('新建会话：2');
  const expected = origin === undefined ? 'http://localhost:8000' : '';
  expect(urls).toEqual([expected + '/api/feedback/admin', expected + '/api/metrics/admin?limit=50']);
});
