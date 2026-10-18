import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import DifficultyPage from './page';

const navigation = vi.hoisted(() => ({ id: 'synthetic', push: vi.fn() }));
vi.mock('next/navigation', () => ({ useParams: () => ({ id: navigation.id }), useRouter: () => ({ push: navigation.push }) }));
beforeEach(() => { navigation.id = 'synthetic'; });
const soup = { id: 'synthetic', title: '合成不限次题目', surface: '合成汤面', tags: ['推理'], difficulty: 2, unlimited: true };
const response = (value: unknown) => new Response(JSON.stringify(value));

test.each([null, undefined])('a valid unbounded catalog renders infinity without inventing a quota: %s', async difficultyLimits => {
  vi.stubGlobal('fetch', async () => response({ soups: [{ ...soup, difficultyLimits }] }));
  render(<DifficultyPage />); await screen.findByText('合成不限次题目');
  expect(screen.getAllByText('∞')).toHaveLength(3);
  fireEvent.click(screen.getByRole('button', { name: /天一/ })); expect(navigation.push).toHaveBeenLastCalledWith('/game/synthetic?level=tianyi');
  fireEvent.click(screen.getByRole('button', { name: '请作者喝杯奶茶' })); expect(navigation.push).toHaveBeenLastCalledWith('/');
});

test('a missing route identity cannot fetch a directory or expose a guessed difficulty choice', () => {
  navigation.id = ''; const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  render(<DifficultyPage />); expect(fetch).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: /许二木/ })).toBeNull();
});

test('a rejected obsolete directory request cannot restore an error on a new route', async () => {
  let reject!: (error: Error) => void; let requests = 0;
  vi.stubGlobal('fetch', () => ++requests === 1 ? new Promise<Response>((_done, fail) => { reject = fail; })
    : Promise.resolve(response({ soups: [{ ...soup, id: 'new-synthetic', title: '新合成题目' }] })));
  const view = render(<DifficultyPage />); await waitFor(() => expect(requests).toBe(1));
  navigation.id = 'new-synthetic'; view.rerender(<DifficultyPage />); await screen.findByText('新合成题目');
  await act(async () => reject(new Error('OLD_PRIVATE_ERROR')));
  expect(screen.queryByRole('alert')).toBeNull(); expect(screen.getByText('新合成题目')).toBeDefined();
});
