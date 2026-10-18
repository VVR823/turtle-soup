import { expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import SiteGate from './SiteGate';
import { getSiteToken, setSiteToken } from '@/lib/api';

const content = <p>Protected boundary content</p>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function deferred() {
  let resolve!: (response: Response) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function submit(value = 'synthetic-new') {
  const input = screen.getByLabelText('访问口令');
  fireEvent.change(input, { target: { value } });
  fireEvent.submit(input.closest('form')!);
}

test('an unlocked site renders children without requesting a catalog', async () => {
  const fetch = vi.fn(async () => json({ siteLocked: false }));
  vi.stubGlobal('fetch', fetch);
  render(<SiteGate>{content}</SiteGate>);
  await screen.findByText('Protected boundary content');
  expect(fetch).toHaveBeenCalledTimes(1);
});

test('a stored token must pass catalog validation before children render', async () => {
  setSiteToken('synthetic-stored');
  const slow = deferred();
  vi.stubGlobal('fetch', async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : slow.promise);
  render(<SiteGate>{content}</SiteGate>);
  await act(async () => {});
  expect(screen.queryByText('Protected boundary content')).toBeNull();
  await act(async () => { slow.resolve(json({ soups: [] })); });
  await screen.findByText('Protected boundary content');
  expect(getSiteToken()).toBe('synthetic-stored');
});

test('a rejected stored token shows the password form instead of protected content', async () => {
  setSiteToken('synthetic-revoked');
  vi.stubGlobal('fetch', async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : json({}, 401));
  render(<SiteGate>{content}</SiteGate>);
  await screen.findByLabelText('访问口令');
  expect(screen.getByRole('alert').textContent).toContain('口令错误');
  expect(screen.queryByText('Protected boundary content')).toBeNull();
});

test('retrying unavailable configuration makes a fresh request and can open the site', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json({}, 503)).mockResolvedValueOnce(json({ siteLocked: false }));
  vi.stubGlobal('fetch', fetch);
  render(<SiteGate>{content}</SiteGate>);
  fireEvent.click(await screen.findByRole('button', { name: '重新检查站点' }));
  await screen.findByText('Protected boundary content');
  expect(fetch).toHaveBeenCalledTimes(2);
});

test('a late configuration response after unmount cannot request a catalog', async () => {
  setSiteToken('synthetic-stored');
  const slow = deferred();
  const fetch = vi.fn(() => slow.promise);
  vi.stubGlobal('fetch', fetch);
  const gate = render(<SiteGate>{content}</SiteGate>);
  gate.unmount();
  await act(async () => { slow.resolve(json({ siteLocked: true })); });
  expect(fetch).toHaveBeenCalledTimes(1);
});

test.each(['resolve', 'reject'])('startup catalog %s after unmount preserves the current token', async outcome => {
  setSiteToken('synthetic-stored');
  const slow = deferred();
  const fetch = vi.fn(async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : slow.promise);
  vi.stubGlobal('fetch', fetch);
  const gate = render(<SiteGate>{content}</SiteGate>);
  await act(async () => {});
  expect(fetch).toHaveBeenCalledTimes(2);
  gate.unmount();
  setSiteToken('synthetic-other-tab');
  await act(async () => {
    if (outcome === 'resolve') slow.resolve(json({ soups: [] }));
    else slow.reject(new Error('Synthetic late catalog failure'));
  });
  expect(getSiteToken()).toBe('synthetic-other-tab');
  expect(fetch).toHaveBeenCalledTimes(2);
});

test('startup storage denial stays unavailable and can recover without persisting a token', async () => {
  vi.stubGlobal('fetch', async () => json({ siteLocked: true }));
  const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('Synthetic storage denial', 'SecurityError');
  });
  try {
    render(<SiteGate>{content}</SiteGate>);
    await screen.findByRole('button', { name: '重新检查站点' });
    expect(screen.queryByText('Protected boundary content')).toBeNull();
  } finally { read.mockRestore(); }
  fireEvent.click(screen.getByRole('button', { name: '重新检查站点' }));
  await screen.findByLabelText('访问口令');
  expect(getSiteToken()).toBe('');
});

test('changing a stored token during startup verification prevents stale unlock', async () => {
  setSiteToken('synthetic-old');
  const slow = deferred();
  vi.stubGlobal('fetch', async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : slow.promise);
  render(<SiteGate>{content}</SiteGate>);
  await act(async () => {});
  setSiteToken('synthetic-other-tab');
  await act(async () => { slow.resolve(json({ soups: [] })); });
  await screen.findByRole('button', { name: '重新检查站点' });
  expect(screen.queryByText('Protected boundary content')).toBeNull();
  expect(getSiteToken()).toBe('synthetic-other-tab');
});

test('whitespace submissions never send catalog validation', async () => {
  const fetch = vi.fn(async () => json({ siteLocked: true }));
  vi.stubGlobal('fetch', fetch);
  render(<SiteGate>{content}</SiteGate>);
  await screen.findByLabelText('访问口令');
  submit('   ');
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(getSiteToken()).toBe('');
});

test('duplicate form submission while validation is pending sends one catalog request', async () => {
  const slow = deferred();
  const fetch = vi.fn(async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : slow.promise);
  vi.stubGlobal('fetch', fetch);
  render(<SiteGate>{content}</SiteGate>);
  await screen.findByLabelText('访问口令');
  submit(); submit();
  expect(fetch).toHaveBeenCalledTimes(2);
  await act(async () => { slow.resolve(json({ soups: [] })); });
  await screen.findByText('Protected boundary content');
});

test('changing token during a submitted validation cannot overwrite the other tab token', async () => {
  const slow = deferred();
  vi.stubGlobal('fetch', async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : slow.promise);
  render(<SiteGate>{content}</SiteGate>);
  await screen.findByLabelText('访问口令');
  submit(); setSiteToken('synthetic-other-tab');
  await act(async () => { slow.resolve(json({ soups: [] })); });
  await screen.findByRole('alert');
  expect(screen.queryByText('Protected boundary content')).toBeNull();
  expect(getSiteToken()).toBe('synthetic-other-tab');
});

test('rejected submitted credentials stay locked and allow another attempt', async () => {
  vi.stubGlobal('fetch', async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : json({}, 401));
  render(<SiteGate>{content}</SiteGate>);
  await screen.findByLabelText('访问口令'); submit();
  expect((await screen.findByRole('alert')).textContent).toContain('口令错误');
  expect((screen.getByRole('button', { name: '进入' }) as HTMLButtonElement).disabled).toBe(false);
  expect(getSiteToken()).toBe('');
});

test('storage write denial after successful verification does not expose protected content', async () => {
  vi.stubGlobal('fetch', async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : json({ soups: [] }));
  render(<SiteGate>{content}</SiteGate>);
  await screen.findByLabelText('访问口令');
  const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('Synthetic storage denial', 'SecurityError');
  });
  try {
    submit();
    await screen.findByRole('alert');
    expect(screen.queryByText('Protected boundary content')).toBeNull();
    expect(getSiteToken()).toBe('');
  } finally { write.mockRestore(); }
  submit();
  await screen.findByText('Protected boundary content');
});

test('a late validation rejection after unmount does not persist credentials', async () => {
  const slow = deferred();
  vi.stubGlobal('fetch', async (input: string | URL | Request) =>
    String(input).endsWith('/api/config') ? json({ siteLocked: true }) : slow.promise);
  const gate = render(<SiteGate>{content}</SiteGate>);
  await screen.findByLabelText('访问口令'); submit(); gate.unmount();
  await act(async () => { slow.reject(new Error('Synthetic late failure')); });
  expect(getSiteToken()).toBe('');
});
