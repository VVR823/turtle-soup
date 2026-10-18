import { expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import SiteGate from './SiteGate';
import { getSiteToken, setSiteToken } from '@/lib/api';

function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }); }
test.each([503, 'json', 'bool'])('config %s never opens children and offers retry', async failure => {
  vi.stubGlobal('fetch', async () => failure === 503 ? json({}, 503) : failure === 'json' ? new Response('not json') : json({ siteLocked: 'false' }));
  render(<SiteGate><p>Protected content</p></SiteGate>);
  await screen.findByRole('button', { name: '重新检查站点' }); expect(screen.queryByText('Protected content')).toBeNull();
});
test('stored token is verified and a service outage preserves it without opening children', async () => {
  setSiteToken('synthetic-old');
  vi.stubGlobal('fetch', async (input: string | URL | Request) => String(input).endsWith('/api/config') ? json({ siteLocked: true }) : json({}, 503));
  render(<SiteGate><p>Protected content</p></SiteGate>);
  await screen.findByRole('button', { name: '重新检查站点' }); expect(getSiteToken()).toBe('synthetic-old');
  expect(screen.queryByText('Protected content')).toBeNull();
});
test.each([503, 'json', 'shape'])('prospective token %s response is not verified or persisted', async failure => {
  vi.stubGlobal('fetch', async (input: string | URL | Request) => String(input).endsWith('/api/config') ? json({ siteLocked: true })
    : failure === 503 ? json({}, 503) : failure === 'json' ? new Response('not json') : json({ soups: {} }));
  render(<SiteGate><p>Protected content</p></SiteGate>); await screen.findByLabelText('访问口令');
  const input = screen.getByLabelText('访问口令'); fireEvent.change(input, { target: { value: 'synthetic-new' } });
  fireEvent.click(screen.getByRole('button', { name: '进入' })); await screen.findByRole('alert');
  expect(getSiteToken()).toBe(''); expect(screen.queryByText('Protected content')).toBeNull();
});
test('an unmounted unlock cannot persist a late token', async () => {
  let resolve!: (response: Response) => void; const slow = new Promise<Response>(done => { resolve = done; });
  vi.stubGlobal('fetch', async (input: string | URL | Request) => String(input).endsWith('/api/config') ? json({ siteLocked: true }) : slow);
  const gate = render(<SiteGate><p>Protected content</p></SiteGate>); await screen.findByLabelText('访问口令');
  fireEvent.change(screen.getByLabelText('访问口令'), { target: { value: 'synthetic-new' } }); fireEvent.click(screen.getByRole('button', { name: '进入' }));
  gate.unmount(); await act(async () => { resolve(json({ soups: [] })); }); expect(getSiteToken()).toBe('');
});
test('successful strict catalog verification persists the token and opens children', async () => {
  vi.stubGlobal('fetch', async (input: string | URL | Request) => String(input).endsWith('/api/config') ? json({ siteLocked: true }) : json({ soups: [] }));
  render(<SiteGate><p>Protected content</p></SiteGate>); await screen.findByLabelText('访问口令');
  fireEvent.change(screen.getByLabelText('访问口令'), { target: { value: 'synthetic-new' } }); fireEvent.click(screen.getByRole('button', { name: '进入' }));
  await screen.findByText('Protected content'); expect(getSiteToken()).toBe('synthetic-new');
});
