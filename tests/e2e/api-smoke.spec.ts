import { expect, test } from '@playwright/test';

test.beforeEach(async ({ request }) => {
  const health = await request.get('/health');
  const fixture = await health.json();
  expect(fixture.testing).toBe(true);
  expect(fixture.provider).toBe('fake');
  expect(fixture.instanceId).toBe(process.env.TURTLE_SOUP_TEST_INSTANCE_ID);
});

test('fixture exposes an isolated healthy seed catalog', async ({ request }) => {
  const health = await request.get('/health');
  expect(health.ok()).toBeTruthy();
  expect((await health.json()).status).toBe('ok');
  const soups = await request.get('/api/soups');
  expect(soups.ok()).toBeTruthy();
  const first = (await soups.json()).soups[0];
  expect(first.id).toBeTruthy();
  expect(first.bottom).toBeUndefined();
});

test('creates and restores only a synthetic temporary session', async ({ request }) => {
  const created = await request.post('/api/chat', { data: { soupId: 'xin', level: 'xuermu' } });
  expect(created.ok()).toBeTruthy();
  const session = await created.json();
  expect(session.questionLimit).toBe(35);
  const restored = await request.get('/api/session/' + session.sessionId);
  expect(restored.ok()).toBeTruthy();
  expect((await restored.json()).questionsAsked).toBe(0);
});

test('ordinary caller cannot read the private feedback list', async ({ request }) => {
  expect((await request.get('/api/feedback/admin')).status()).toBe(401);
  const approved = await request.get('/api/feedback/admin', {
    headers: { 'X-Admin-Token': 'e2e-test-only' },
  });
  expect(approved.ok()).toBeTruthy();
  const bounded = await approved.json();
  expect(bounded.totalInRange).toBe(0);
  expect(bounded.feedbacks).toEqual([]);
  expect(bounded.nextCursor).toBeNull();
});
