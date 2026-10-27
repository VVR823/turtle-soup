import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import MetricsPanel from './MetricsPanel';

test('technical filters are collapsed while the default query remains available', () => {
  render(<MetricsPanel adminToken="synthetic-admin" />);
  expect(screen.getByLabelText('题目ID').closest('details')?.open).toBe(false);
  expect(screen.getByRole('button', { name: '查询统计' }).hasAttribute('disabled')).toBe(false);
  fireEvent.click(screen.getByText('高级筛选（通常不用填写）'));
  expect(screen.getByLabelText('题目ID').closest('details')?.open).toBe(true);
});

test.each(['10000-01-01T00:00', '275761-01-01T00:00'])('a valid date-input value outside Date.parse support is refused before fetching: %s', async value => {
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  render(<MetricsPanel adminToken="synthetic-admin" />);
  const input = screen.getByLabelText('开始时间（UTC）') as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
  expect(input.value).toBe(value);
  expect(Number.isFinite(Date.parse(value + 'Z'))).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '查询统计' }));
  expect((await screen.findByRole('alert')).textContent).toContain('统计数据暂时无法核验');
  expect(fetch).not.toHaveBeenCalled();
});
