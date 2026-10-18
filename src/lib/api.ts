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
  if (token && !headers.has('X-Site-Token')) headers.set('X-Site-Token', token);
  if (!headers.has('Content-Type') && (init.method || 'GET') !== 'GET') {
    headers.set('Content-Type', 'application/json');
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    // A late response only owns the credential actually sent, not a newly
    // verified token or a different stored token during a prospective check.
    if (getSiteToken() === (headers.get('X-Site-Token') || '')) clearSiteToken();
    throw new ApiAuthError();
  }
  return res;
}

export class ApiProtocolError extends Error {
  constructor() { super('服务返回的数据暂时无法读取，请同步原对局'); this.name = 'ApiProtocolError'; }
}

export class ApiHttpError extends Error {
  constructor(public readonly status: number, public readonly code: string | null,
    public readonly requestId: string | null, public readonly retryAfterSeconds: number | null) {
    super(({ 404: '保存的对局或请求不存在', 410: '这局旧游戏暂时无法恢复，历史仍保留',
      409: '对局状态已变化，请同步后再操作', 429: '请求较多，请稍后同步', 503: '服务暂时不可用，请稍后同步' } as Record<number, string>)[status]
      || `请求失败（${status}），请保留原对局并重试`);
    this.name = 'ApiHttpError';
  }
}

export interface ApiJsonResponse { status: number; ok: boolean; body: unknown; headers: Headers }

export async function apiResponseJson(path: string, init: RequestInit = {}): Promise<ApiJsonResponse> {
  const response = await apiFetch(path, init);
  let body: unknown;
  try { body = await response.json(); } catch {
    if (!response.ok) throw httpError({ status: response.status, ok: false, body: null, headers: response.headers });
    throw new ApiProtocolError();
  }
  return { status: response.status, ok: response.ok, body, headers: response.headers };
}

export function httpError(response: ApiJsonResponse): ApiHttpError {
  const body = response.body && typeof response.body === 'object' && !Array.isArray(response.body)
    ? response.body as Record<string, unknown> : {};
  const raw = response.headers.get('Retry-After');
  const seconds = !raw ? null : /^\d+(?:\.\d+)?$/.test(raw) ? Math.ceil(Number(raw))
    : Number.isFinite(Date.parse(raw)) ? Math.max(0, Math.ceil((Date.parse(raw) - Date.now()) / 1000)) : null;
  return new ApiHttpError(response.status, typeof body.code === 'string' ? body.code : null,
    typeof body.requestId === 'string' ? body.requestId : null,
    seconds !== null && Number.isSafeInteger(seconds) ? seconds : null);
}

export async function apiJson(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await apiResponseJson(path, init);
  if (!response.ok) throw httpError(response);
  return response.body;
}
