import { expect, test, vi } from 'vitest';

const asked = vi.hoisted(() => [] as string[]);
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/api/auth.svelte')>()),
  authFetch: async (path: string) => { asked.push(path); return { groups: [] }; },
}));

const { PER_CONVERSATION_ALL, PER_GROUP, groupedSearchApi, readAnswer } = await import('./deepsearch-api');

test('from_backup, entry_uuid, family and the stale list are kept, and an absent one is never invented', () => {
  const answer = readAnswer({
    stale: ['c-old', '', 7],
    groups: [{ conversation_id: 'c1', family: 'codex', hits: [
      { snippet: 'a', from_backup: true, entry_uuid: 'u-1' },
      { snippet: 'b' },
    ] }],
  });
  expect(answer.stale).toEqual(['c-old']);
  const g = answer.groups[0]!;
  expect(g.family).toBe('codex');
  expect(g.hits.map((h) => [h.fromBackup, h.entryUuid])).toEqual([[true, 'u-1'], [false, null]]);
  expect(readAnswer({}).stale).toEqual([]);
  expect(readAnswer({ groups: [{ conversation_id: 'c1', hits: [{ snippet: 'a', from_backup: 'yes' }] }] }).groups[0]!.hits[0]!.fromBackup).toBe(false);
});

test('the exported status is kept as sent, and an absent or malformed one is null, never invented', () => {
  const answer = readAnswer({ groups: [
    { conversation_id: 'c1', hits: [], exported: { bundle_id: 'crate-1', label: 'october', exported_at: '2026-10-17T00:00:00+00:00', local_removed: true } },
    { conversation_id: 'c2', hits: [], exported: { bundle_id: 'crate-2' } },
    { conversation_id: 'c3', hits: [] },
    { conversation_id: 'c4', hits: [], exported: { label: 'no id' } },
    { conversation_id: 'c5', hits: [], exported: 'yes' },
  ] });
  expect(answer.groups.map((g) => g.exported)).toEqual([
    { bundleId: 'crate-1', label: 'october', exportedAt: '2026-10-17T00:00:00+00:00', localRemoved: true },
    { bundleId: 'crate-2', label: null, exportedAt: null, localRemoved: false },
    null, null, null,
  ]);
});

test('kinds and conversation_id are sent only to a route that honors them', async () => {
  asked.length = 0;
  const signal = new AbortController().signal;
  await groupedSearchApi('/deepsearch/search', { scope: 'local' }, true).search('rsync', 0, signal, { kinds: 'user' });
  await groupedSearchApi('/deepsearch/search', {}, true).search('rsync', 0, signal, { conversationId: 'c1' });
  await groupedSearchApi('/pipeline/prompts/search').search('rsync', 0, signal, { kinds: 'user', conversationId: 'c1' });
  const query = (i: number) => new URLSearchParams(asked[i]!.split('?')[1]);
  expect(query(0).get('kinds')).toBe('user');
  expect(query(0).get('per_group')).toBe(String(PER_GROUP));
  expect(query(1).get('conversation_id')).toBe('c1');
  expect(query(1).get('per_group')).toBe(String(PER_CONVERSATION_ALL));
  expect(query(2).has('kinds') || query(2).has('conversation_id')).toBe(false);
});
