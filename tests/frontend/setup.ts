import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

beforeEach(() => {
  localStorage.clear();
  vi.stubEnv('NEXT_PUBLIC_API_BASE', 'http://127.0.0.1:18080');
  // Individual unit tests must replace this with their own deterministic fetch.
  vi.stubGlobal('fetch', () => {
    throw new Error('Real fetch is disabled in frontend unit tests');
  });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
