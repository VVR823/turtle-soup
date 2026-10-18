import { expect, test, vi } from 'vitest';
import { loadPublicCatalog } from './catalog';
import { GameContractError } from './game-contract';

const soup = { id: 'synthetic', title: 'Public', surface: 'Public story', tags: ['合成'], difficulty: 2 };
function directory(soups: unknown[]) {
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ soups })));
}

test.each([
  ['empty id', { id: ' ' }], ['oversized id', { id: 'x'.repeat(201) }],
  ['blank title', { title: ' ' }], ['non-text surface', { surface: null }],
  ['missing tags', { tags: null }], ['fractional difficulty', { difficulty: 1.5 }],
  ['difficulty below range', { difficulty: 0 }], ['difficulty above range', { difficulty: 6 }],
  ['non-boolean hidden flag', { hidden: 'true' }], ['non-boolean unlimited flag', { unlimited: 1 }],
  ['non-text source', { source: null }], ['array limits', { difficultyLimits: [] }],
  ['scalar limits', { difficultyLimits: 3 }], ['missing limits', { difficultyLimits: {} }],
  ['zero limit', { difficultyLimits: { xuermu: 0, baozi: 2, tianyi: 3 } }],
  ['negative limit', { difficultyLimits: { xuermu: 1, baozi: -2, tianyi: 3 } }],
  ['fractional limit', { difficultyLimits: { xuermu: 1, baozi: 2, tianyi: 0.5 } }],
  ['text limit', { difficultyLimits: { xuermu: '1', baozi: 2, tianyi: 3 } }],
  ['unsafe integer limit', { difficultyLimits: { xuermu: Number.MAX_SAFE_INTEGER + 1, baozi: 2, tianyi: 3 } }],
])('%s rejects the catalog without treating malformed metadata as a valid choice', async (_name, changes) => {
  directory([{ ...soup, ...changes }]);
  await expect(loadPublicCatalog()).rejects.toBeInstanceOf(GameContractError);
});

test.each([null, [], 4])('non-object catalog entry %j refuses the whole directory', async item => {
  directory([soup, item]);
  await expect(loadPublicCatalog()).rejects.toBeInstanceOf(GameContractError);
});

test('valid public metadata retains false flags and explicit limits while stripping private fields', async () => {
  const publicMetadata = { ...soup, id: 'x'.repeat(200), hidden: false, unlimited: false,
    source: 'Authorized synthetic source', difficultyLimits: { xuermu: 1, baozi: 2, tianyi: 3 } };
  directory([{ ...publicMetadata, bottom: 'Private truth', bottomSummary: 'Private summary',
    trace: { secret: 'Synthetic private trace' }, adminToken: 'Synthetic private credential' }]);
  expect(await loadPublicCatalog()).toEqual([publicMetadata]);
});
