import { expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import AdminFeedbackPage from './page';

test('late401 from the previous admin credential cannot clear a newer credential', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-old'); let resolve!: (response: Response) => void;
  const slow = new Promise<Response>(done => { resolve = done; });
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => new Headers(init?.headers).get('X-Admin-Token') === 'synthetic-old'
    ? slow : new Response(JSON.stringify({ totalInRange: 0, nextCursor: null, feedbacks: [] })));
  render(<AdminFeedbackPage />);
  await act(async () => { localStorage.setItem('turtle_admin_token', 'synthetic-new'); window.dispatchEvent(new StorageEvent('storage', { key: 'turtle_admin_token' })); });
  await act(async () => { resolve(new Response('{}', { status: 401 })); });
  expect(localStorage.getItem('turtle_admin_token')).toBe('synthetic-new');
});
test('late401 after unmount cannot mutate the saved credential', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin'); let resolve!: (response: Response) => void;
  const slow = new Promise<Response>(done => { resolve = done; }); vi.stubGlobal('fetch', async () => slow);
  const page = render(<AdminFeedbackPage />); page.unmount(); await act(async () => { resolve(new Response('{}', { status: 401 })); });
  expect(localStorage.getItem('turtle_admin_token')).toBe('synthetic-admin');
});

test('no saved admin credential displays the prompt without a request', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); render(<AdminFeedbackPage />);
  await screen.findByPlaceholderText('管理口令'); expect(fetch).not.toHaveBeenCalled();
});
test('a saved synthetic admin credential is used for initial verification', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  vi.stubGlobal('fetch', async (_input: string | URL | Request, init?: RequestInit) => {
    expect(new Headers(init?.headers).get('X-Admin-Token')).toBe('synthetic-admin');
    return new Response(JSON.stringify({ totalInRange: 0, nextCursor: null, feedbacks: [] }));
  });
  render(<AdminFeedbackPage />); await screen.findByText('还没有玩家提交反馈。');
});
test('removing the browser credential through a storage event returns to the prompt', async () => {
  localStorage.setItem('turtle_admin_token', 'synthetic-admin');
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ totalInRange: 0, nextCursor: null, feedbacks: [] })));
  render(<AdminFeedbackPage />); await screen.findByText('还没有玩家提交反馈。');
  await act(async () => { localStorage.removeItem('turtle_admin_token'); window.dispatchEvent(new StorageEvent('storage', { key: 'turtle_admin_token' })); });
  await screen.findByPlaceholderText('管理口令');
});
test('entered synthetic credential starts one verification request', async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ totalInRange: 0, nextCursor: null, feedbacks: [] }))); vi.stubGlobal('fetch', fetch);
  render(<AdminFeedbackPage />); await screen.findByPlaceholderText('管理口令');
  fireEvent.change(screen.getByPlaceholderText('管理口令'), { target: { value: 'synthetic-admin' } });
  fireEvent.click(screen.getByRole('button', { name: '进入' })); await screen.findByText('还没有玩家提交反馈。'); expect(fetch).toHaveBeenCalledTimes(1);
});
