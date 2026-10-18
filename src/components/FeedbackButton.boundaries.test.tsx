import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import FeedbackButton from './FeedbackButton';

const route = vi.hoisted(() => ({ pathname: '/' }));
vi.mock('next/navigation', () => ({ usePathname: () => route.pathname }));
beforeEach(() => { route.pathname = '/'; });
const source = { soupId: 'synthetic', soupTitle: '', turnId: 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa',
  question: '合成问题', hostAnswer: '不是' };
const openBound = () => {
  render(<FeedbackButton source={source} />);
  fireEvent.click(screen.getByRole('button', { name: '反馈这次回答' }));
  fireEvent.change(screen.getByText('请选择标准答案…').closest('select')!, { target: { value: '是' } });
};

test('admin navigation hides the feedback control and returning restores it without changing hook order', () => {
  const view = render(<FeedbackButton />);
  expect(screen.getByRole('button')).toBeDefined();
  route.pathname = '/admin/feedback'; view.rerender(<FeedbackButton />);
  expect(screen.queryByRole('button')).toBeNull();
  route.pathname = '/'; view.rerender(<FeedbackButton />);
  expect(screen.getByRole('button')).toBeDefined();
});

test.each(['input', 'textarea', 'select'])('focused %s hides the floating control and blur restores it', tag => {
  render(<FeedbackButton />);
  const control = screen.getByRole('button');
  const field = document.createElement(tag);
  document.body.append(field);
  try {
    fireEvent.focusIn(field);
    expect(control.className).toContain('pointer-events-none');
    fireEvent.focusOut(field);
    expect(control.className).not.toContain('pointer-events-none');
  } finally { field.remove(); }
});

test('focus on ordinary content does not hide the feedback control', () => {
  render(<FeedbackButton />);
  fireEvent.focusIn(document.body);
  expect(screen.getByRole('button').className).not.toContain('pointer-events-none');
});

test.each([
  { response: () => new Response(JSON.stringify({ detail: '合成服务拒绝' }), { status: 503 }), message: '合成服务拒绝' },
  { response: () => new Response('not json', { status: 503 }), message: '提交失败' },
  { response: () => { throw new Error('合成网络错误'); }, message: '合成网络错误' },
  { response: () => { throw 'synthetic failure'; }, message: '提交失败，请稍后重试' },
])('failed submission retains the form and permits an explicit retry: $message', async ({ response, message }) => {
  const fetch = vi.fn(response);
  vi.stubGlobal('fetch', fetch);
  openBound();
  expect(screen.getByRole('option', { name: 'synthetic' })).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: '提交反馈' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
  expect(screen.queryByText('✅ 提交成功，感谢反馈！')).toBeNull();
  expect((screen.getByRole('button', { name: '提交反馈' }) as HTMLButtonElement).disabled).toBe(false);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test('bound feedback trims optional reasons, acknowledges success and clears the next form', async () => {
  const fetch = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  openBound();
  fireEvent.change(screen.getByPlaceholderText('可补充为什么你认为主持人答错了'), { target: { value: '  合成理由  ' } });
  fireEvent.click(screen.getByRole('button', { name: '提交反馈' }));
  await screen.findByText('✅ 提交成功，感谢反馈！');
  const payload = JSON.parse(fetch.mock.calls[0][1]!.body as string);
  expect(payload).toMatchObject({ reason: '合成理由', turnId: source.turnId, expectedAnswer: '是' });
  fireEvent.click(screen.getByText('关闭', { exact: true }));
  fireEvent.click(screen.getByRole('button', { name: '反馈这次回答' }));
  expect((screen.getByPlaceholderText('可补充为什么你认为主持人答错了') as HTMLTextAreaElement).value).toBe('');
  expect((screen.getByRole('button', { name: '提交反馈' }) as HTMLButtonElement).disabled).toBe(true);
});

test('an empty validated catalog disables submission instead of inventing soup choices', async () => {
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ soups: [] })));
  render(<FeedbackButton />);
  fireEvent.click(screen.getByRole('button'));
  await screen.findByText('暂时没有可选择的汤品。');
  expect((screen.getByRole('button', { name: '提交反馈' }) as HTMLButtonElement).disabled).toBe(true);
});

test.each(['resolve', 'reject'] as const)('closing a pending catalog aborts ownership and ignores its late %s', async outcome => {
  let resolve!: (value: Response) => void;
  let reject!: (error: Error) => void;
  let signal: AbortSignal | undefined;
  vi.stubGlobal('fetch', (_input: unknown, init?: RequestInit) => {
    signal = init?.signal ?? undefined;
    return new Promise<Response>((done, fail) => { resolve = done; reject = fail; });
  });
  render(<FeedbackButton />);
  fireEvent.click(screen.getByRole('button'));
  expect(signal?.aborted).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(signal?.aborted).toBe(true);
  await act(async () => {
    if (outcome === 'resolve') resolve(new Response(JSON.stringify({ soups: [] })));
    else reject(new Error('late synthetic catalog error'));
  });
  expect(screen.queryByText('提交主持人回答 Bug')).toBeNull();
  expect(screen.queryByRole('alert')).toBeNull();
});
