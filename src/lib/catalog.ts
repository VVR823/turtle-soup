/** Only a successful, validated public directory is an empty directory. */
import { apiJson, getUnlockedSoups } from './api';
import { GameContractError } from './game-contract';

export interface PublicSoup {
  id: string; title: string; surface: string; tags: string[]; difficulty: number; source?: string;
  hidden?: boolean; unlimited?: boolean; difficultyLimits?: { xuermu: number; baozi: number; tianyi: number } | null;
}
export async function loadPublicCatalog({ query = '', signal, token }: { query?: string; signal?: AbortSignal; token?: string } = {}): Promise<PublicSoup[]> {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  const unlocked = getUnlockedSoups();
  if (unlocked.length) params.set('unlocked', unlocked.join(','));
  const body = await apiJson('/api/soups' + (params.size ? '?' + params.toString() : ''), {
    signal, ...(token !== undefined ? { headers: { 'X-Site-Token': token } } : {}),
  });
  if (!body || typeof body !== 'object' || Array.isArray(body) || !Array.isArray((body as { soups?: unknown }).soups)) throw new GameContractError('汤品列表暂时无法核验，请重试');
  return (body as { soups: unknown[] }).soups.map(input => {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new GameContractError();
    const item = input as Record<string, unknown>;
    if (typeof item.id !== 'string' || !item.id.trim() || item.id.length > 200 || typeof item.title !== 'string'
        || !item.title.trim() || typeof item.surface !== 'string' || !Array.isArray(item.tags) || item.tags.some(tag => typeof tag !== 'string')
        || typeof item.difficulty !== 'number' || !Number.isSafeInteger(item.difficulty) || item.difficulty < 1 || item.difficulty > 5) throw new GameContractError();
    const result: PublicSoup = { id: item.id, title: item.title, surface: item.surface, tags: [...item.tags], difficulty: item.difficulty };
    for (const field of ['hidden', 'unlimited'] as const) {
      if (item[field] !== undefined) {
        if (typeof item[field] !== 'boolean') throw new GameContractError();
        result[field] = item[field];
      }
    }
    if (item.source !== undefined) {
      if (typeof item.source !== 'string') throw new GameContractError();
      result.source = item.source;
    }
    if (item.difficultyLimits !== undefined) {
      if (item.difficultyLimits === null) result.difficultyLimits = null;
      else {
        const limits = item.difficultyLimits as Record<string, unknown>;
        if (!limits || typeof limits !== 'object' || Array.isArray(limits)
            || !['xuermu', 'baozi', 'tianyi'].every(key => typeof limits[key] === 'number' && Number.isSafeInteger(limits[key]) && (limits[key] as number) > 0)) throw new GameContractError();
        result.difficultyLimits = { xuermu: limits.xuermu as number, baozi: limits.baozi as number, tianyi: limits.tianyi as number };
      }
    }
    return result;
  });
}
