// 前端直连的 Python 后端地址（FastAPI，默认 :8000）。
// 开发：不设置 NEXT_PUBLIC_API_BASE → 用 http://localhost:8000
// 部署：设置 NEXT_PUBLIC_API_BASE 为空字符串 "" → 用相对路径 /api（由 nginx 反代到后端）
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE !== undefined
    ? process.env.NEXT_PUBLIC_API_BASE
    : 'http://localhost:8000';

const TOKEN_KEY = 'site_token';
const UNLOCKED_KEY = 'unlocked_soups';

export function getSiteToken(): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setSiteToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearSiteToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
}

/** 已解锁的隐藏彩蛋汤 id 列表（本地存储，换设备会丢） */
export function getUnlockedSoups(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(UNLOCKED_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((s): s is string => typeof s === 'string') : [];
  } catch {
    return [];
  }
}

export function addUnlockedSoup(soupId: string): void {
  if (typeof window === 'undefined') return;
  const current = new Set(getUnlockedSoups());
  current.add(soupId);
  localStorage.setItem(UNLOCKED_KEY, JSON.stringify(Array.from(current)));
}

export function clearUnlockedSoups(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(UNLOCKED_KEY);
}

// —— 上一局会话（刷新/重开页面后恢复，不丢进度）——
const LAST_SESSION_KEY = 'last_session';

export interface LastSession {
  sessionId: string;
  soupId: string;
  level: string;
}

export function saveLastSession(s: LastSession | null): void {
  if (typeof window === 'undefined') return;
  if (!s) {
    localStorage.removeItem(LAST_SESSION_KEY);
    return;
  }
  localStorage.setItem(LAST_SESSION_KEY, JSON.stringify(s));
}

export function getLastSession(): LastSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(LAST_SESSION_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    if (s && typeof s.sessionId === 'string' && typeof s.soupId === 'string') return s;
    return null;
  } catch {
    return null;
  }
}

// —— 玩过的汤（口径：完整用完全部提问次数，或看过答案/汤底，才算玩过）——
const PLAYED_KEY = 'played_soups';

export function getPlayedSoups(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(PLAYED_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((s): s is string => typeof s === 'string') : [];
  } catch {
    return [];
  }
}

export function addPlayedSoup(soupId: string): void {
  if (typeof window === 'undefined') return;
  const set = new Set(getPlayedSoups());
  set.add(soupId);
  localStorage.setItem(PLAYED_KEY, JSON.stringify(Array.from(set)));
}

/** 401（口令错误/缺失）时抛出的错误，便于上层跳回解锁界面。 */
export class ApiAuthError extends Error {
  constructor(message = '需要访问口令') {
    super(message);
    this.name = 'ApiAuthError';
  }
}

/**
 * 统一的 fetch 封装：自动携带 X-Site-Token（若已保存），
 * 遇到 401 抛出 ApiAuthError，上层据此清理令牌并回到锁屏。
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getSiteToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('X-Site-Token', token);
  if (!headers.has('Content-Type') && (init.method || 'GET') !== 'GET') {
    headers.set('Content-Type', 'application/json');
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearSiteToken();
    throw new ApiAuthError();
  }
  return res;
}
