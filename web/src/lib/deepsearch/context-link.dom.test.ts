/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const wire = vi.hoisted(() => ({ opened: [] as Array<Record<string, unknown>>, auth: { state: 'signed-out' } }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/api/auth.svelte')>()),
  auth: wire.auth,
}));
vi.mock('../modal', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../modal')>()),
  openModal: async (_component: unknown, props: Record<string, unknown>) => { wire.opened.push(props); },
}));

const { openLinkFromHash } = await import('./context-link.svelte');

beforeEach(() => { wire.opened = []; wire.auth.state = 'signed-out'; window.location.hash = ''; });
afterEach(() => { window.location.hash = ''; });

test('a link opens the context modal for its line once signed in, then the hash is cleared', () => {
  window.location.hash = '#deepsearch/context?c=conv-1&l=4&k=subagent';
  openLinkFromHash();
  expect(wire.opened, 'not signed in yet: nothing opens and the link waits').toHaveLength(0);
  expect(window.location.hash).toBe('#deepsearch/context?c=conv-1&l=4&k=subagent');
  wire.auth.state = 'signed-in';
  openLinkFromHash();
  expect(wire.opened).toHaveLength(1);
  expect(wire.opened[0]).toMatchObject({ request: { conversationId: 'conv-1', fileKind: 'subagent', line: 4, hostKey: null }, focus: 'hit', hitLine: 4 });
  expect(window.location.hash).toBe('');
  openLinkFromHash();
  expect(wire.opened, 'cleared: a refresh or Back does not reopen it').toHaveLength(1);
});

test('a hash that is not a link is left alone', () => {
  wire.auth.state = 'signed-in';
  window.location.hash = '#projects/3';
  openLinkFromHash();
  expect(wire.opened).toHaveLength(0);
  expect(window.location.hash).toBe('#projects/3');
});
