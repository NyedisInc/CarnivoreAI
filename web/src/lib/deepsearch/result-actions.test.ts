import { beforeEach, expect, test, vi } from 'vitest';

const calls = vi.hoisted(() => [] as Array<{ path: string; init: { method?: string; body?: string } }>);

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/api/auth.svelte')>()),
  authFetch: async (path: string, init: { method?: string; body?: string }) => {
    calls.push({ path, init });
    return { session: { id: 'ses_new', tmux_session: 'carnivore_new' } };
  },
}));

const { bookmarkAt, branchAt, copyText, linkUrl, resumeSession } = await import('./result-actions');

beforeEach(() => { calls.length = 0; });

test('resume restarts the stopped session by its uuid', async () => {
  await resumeSession('a/b');
  expect(calls).toEqual([{ path: '/sessions/a%2Fb/restart', init: { method: 'POST', body: '{}' } }]);
});

test('branch cuts at the message and names its conversation; the new session comes back', async () => {
  const made = await branchAt('s1', 'u-7', 'conv-1');
  expect(made).toEqual({ sessionId: 'ses_new', tmuxName: 'carnivore_new' });
  expect(calls[0]!.path).toBe('/sessions/s1/branch');
  expect(JSON.parse(calls[0]!.init.body!)).toEqual({ entry_uuid: 'u-7', conversation: 'conv-1' });
});

test('bookmark marks the message', async () => {
  await bookmarkAt('s1', 'u-7');
  expect(calls[0]!.path).toBe('/sessions/s1/bookmarks');
  expect(JSON.parse(calls[0]!.init.body!)).toEqual({ entry_uuid: 'u-7' });
});

test('the link is this page plus the hash, and copying reports whether it worked', async () => {
  const page = { origin: 'http://localhost:5001', pathname: '/', search: '?x=1' };
  expect(linkUrl({ conversationId: 'c1', line: 3, fileKind: 'conversation', hostKey: null }, page)).toBe('http://localhost:5001/?x=1#deepsearch/context?c=c1&l=3');
  const written: string[] = [];
  vi.stubGlobal('navigator', { clipboard: { writeText: async (t: string) => { written.push(t); } } });
  expect(await copyText('hello')).toBe(true);
  expect(written).toEqual(['hello']);
  vi.stubGlobal('navigator', { clipboard: { writeText: async () => { throw new Error('denied'); } } });
  expect(await copyText('hello')).toBe(false);
  vi.unstubAllGlobals();
});
