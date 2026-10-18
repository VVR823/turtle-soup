import { expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import SiteGate from './SiteGate';
import { getSiteToken } from '@/lib/api';

// A submit-time storage read escaping catch would reject the handler without an alert.
test('token read failure stays locked without verification and permits retry after storage recovers', async () => {
  const fetch = vi.fn<typeof globalThis.fetch>(async input => new Response(JSON.stringify(
    String(input).endsWith('/api/config') ? { siteLocked: true } : { soups: [] },
  ), { status: 200 }));
  vi.stubGlobal('fetch', fetch);
  render(<SiteGate><p>Protected content</p></SiteGate>);
  await screen.findByLabelText('访问口令');
  fireEvent.change(screen.getByLabelText('访问口令'), { target: { value: 'synthetic-new' } });
  const originalGet = Storage.prototype.getItem;
  const inaccessible = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key) {
    if (key === 'site_token') throw new DOMException('Synthetic token storage denied', 'SecurityError');
    return originalGet.call(this, key);
  });
  try {
    fireEvent.click(screen.getByRole('button', { name: '进入' }));
    expect((await screen.findByRole('alert')).textContent).toContain('验证未完成');
    expect(screen.queryByText('Protected content')).toBeNull();
    expect((screen.getByRole('button', { name: '进入' }) as HTMLButtonElement).disabled).toBe(false);
    expect(fetch.mock.calls.map(args => new URL(String(args[0])).pathname)).toEqual(['/api/config']);
  } finally { inaccessible.mockRestore(); }
  expect(getSiteToken()).toBe('');
  fireEvent.click(screen.getByRole('button', { name: '进入' }));
  await screen.findByText('Protected content');
  expect(getSiteToken()).toBe('synthetic-new');
  expect(fetch.mock.calls.map(args => new URL(String(args[0])).pathname)).toEqual(['/api/config', '/api/soups']);
});
