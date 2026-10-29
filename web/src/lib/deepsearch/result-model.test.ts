import { expect, test } from 'vitest';
import { readAnswer, type DeepGroup, type DeepHit } from './deepsearch-api';
import {
  DEFAULT_LAYOUT, LAYOUT_KEY, conversationName, conversationState, countLine, hiddenCount, hitActions, hitClock, ledKind, needsFetch,
  readLayout, relativeWhen, splitActions, staleLine, startIndexes, visibleHits, walk, writeLayout, type Tr,
} from './result-model';

const tr: Tr = (key, params) => (params ? `${key.replace('deepsearch.', '')}${JSON.stringify(params)}` : key.replace('deepsearch.', ''));

const hitOf = (extra: Record<string, unknown> = {}): Record<string, unknown> => ({ line: 3, kind: 'user', snippet: 'x \u0002y\u0003', file_kind: 'conversation', entry_uuid: 'u1', ...extra });
const groupOf = (extra: Record<string, unknown> = {}, hits: Array<Record<string, unknown>> = [hitOf(), hitOf({ line: 4 }), hitOf({ line: 5 })]): DeepGroup =>
  readAnswer({ groups: [{ conversation_id: 'c1', matches: 3, hits, ...extra }] }).groups[0]!;

test('the name ladder: session name, else the first prompt on one line, else the folder, never a bare id', () => {
  expect(conversationName(groupOf({ session: 'nightly fix', first_prompt: 'p', working_dir: '/a/b' }), null, tr)).toBe('nightly fix');
  expect(conversationName(groupOf({ session: 'nightly fix' }), 'live name', tr)).toBe('live name');
  expect(conversationName(groupOf({ first_prompt: 'plex  is\npegging the cpu', working_dir: '/a/media-stack' }), null, tr)).toBe('plex is pegging the cpu');
  const long = 'word '.repeat(40);
  const cut = conversationName(groupOf({ first_prompt: long }), null, tr);
  expect(cut.endsWith('...')).toBe(true);
  expect(cut.length).toBeLessThanOrEqual(83);
  expect(conversationName(groupOf({ working_dir: '/Users/x/media-stack/' }), null, tr)).toBe('media-stack');
  expect(conversationName(groupOf({ session: '3f2a9c1e-1111-2222-3333-444455556666', working_dir: '/a/homelab' }), null, tr)).toBe('homelab');
  expect(conversationName(groupOf({ session: 'deadbeefdeadbeef' }), null, tr)).toBe('untitled');
});

test('a state per conversation: computer, backup, live, asleep, none', () => {
  const live = { activity_status: 'working' };
  expect(conversationState(groupOf({ host_key: 'peer-mini', session_uuid: 's' }), live)).toBe('computer');
  expect(conversationState(groupOf({ host_key: 'local' }), undefined)).toBe('none');
  expect(conversationState(groupOf({ session_uuid: 's' }, [hitOf({ from_backup: true })]), live)).toBe('backup');
  expect(conversationState(groupOf({ session_uuid: 's' }), live)).toBe('live');
  expect(conversationState(groupOf({ session_uuid: 's' }), { activity_status: 'dead' })).toBe('asleep');
  expect(conversationState(groupOf({ session_uuid: 's' }), undefined)).toBe('asleep');
  expect(conversationState(groupOf(), undefined)).toBe('none');
});

test('the light: the real one for live, a ring for a stopped session, a dash otherwise', () => {
  const g = groupOf({ session_uuid: 's' });
  expect(ledKind('live', g)).toBe('live');
  expect(ledKind('asleep', g)).toBe('ring');
  expect(ledKind('backup', g)).toBe('ring');
  expect(ledKind('backup', groupOf())).toBe('dash');
  expect(ledKind('none', g)).toBe('dash');
  expect(ledKind('computer', g)).toBe('dash');
});

test('one relative date style: just now, minutes, hours, yesterday, then the date (year only when not this one)', () => {
  const now = new Date('2026-10-15T12:00:00');
  expect(relativeWhen('2026-10-15T11:59:40', now, tr)).toBe('when.now');
  expect(relativeWhen('2026-10-15T11:48:00', now, tr)).toBe('when.minutes{"n":12}');
  expect(relativeWhen('2026-10-15T10:00:00', now, tr)).toBe('when.hours{"n":2}');
  expect(relativeWhen('2026-10-14T23:00:00', now, tr)).toBe('when.yesterday');
  expect(relativeWhen('2026-10-09T08:00:00', now, tr)).toBe('oct 9');
  expect(relativeWhen('2025-10-09T08:00:00', now, tr)).toBe('oct 9 2025');
  expect(relativeWhen(null, now, tr)).toBe('');
  expect(relativeWhen('not a date', now, tr)).toBe('');
  expect(hitClock('2026-10-15T08:31:00', now)).toBe('08:31');
  expect(hitClock('2026-10-14T08:31:00', now)).toBe('oct 14');
});

test('hits shown, hits hidden, and when the server must be asked', () => {
  const g = groupOf({ matches: 7 });
  expect(visibleHits(g, false)).toHaveLength(2);
  expect(visibleHits(g, true)).toHaveLength(3);
  expect(hiddenCount(g, false)).toBe(5);
  expect(hiddenCount(g, true)).toBe(4);
  expect(needsFetch(g)).toBe(true);
  expect(needsFetch(groupOf({ matches: 3 }))).toBe(false);
  const remote = groupOf({ matches: 9, host_key: 'peer-mini' });
  expect(needsFetch(remote)).toBe(false);
  expect(hiddenCount(remote, false)).toBe(1);
  expect(hiddenCount(remote, true)).toBe(0);
});

test('the arrows walk the visible hits and the views number them the same way', () => {
  const a = groupOf({ conversation_id: 'a', matches: 3 });
  const b = { ...groupOf({ conversation_id: 'b', matches: 3 }), conversationId: 'b' };
  expect(walk([a, b], {}).map((w) => `${w.group.conversationId}${w.index}`)).toEqual(['a0', 'a1', 'b2', 'b3']);
  expect(walk([a, b], { a: true }).map((w) => w.index)).toEqual([0, 1, 2, 3, 4]);
  expect(startIndexes([a, b], {})).toEqual({ a: 0, b: 2 });
  expect(startIndexes([a, b], { a: true })).toEqual({ a: 0, b: 3 });
});

test('counts say hit and hits honestly, and stale is one line', () => {
  expect(countLine(9, 5, tr)).toBe('count{"hits":"hits_many{\\"count\\":9}","conversations":"conversations_many{\\"count\\":5}"}');
  expect(countLine(1, 1, tr)).toContain('hits_one');
  expect(countLine(1, 1, tr)).toContain('conversations_one');
  expect(staleLine(0, tr)).toBe('');
  expect(staleLine(1, tr)).toBe('stale_one{"count":1}');
  expect(staleLine(3, tr)).toBe('stale_many{"count":3}');
});

test('actions: a session-bound hit gets go or resume, branch and bookmark; no session, a backup or another computer only reads and links', () => {
  const g = groupOf({ session_uuid: 's' });
  const hit = g.hits[0]!;
  expect(hitActions('live', g, hit)).toEqual(['read', 'go', 'branch', 'link', 'bookmark', 'scope']);
  expect(hitActions('asleep', g, hit)).toEqual(['read', 'resume', 'branch', 'link', 'bookmark', 'scope']);
  for (const state of ['none', 'backup', 'computer'] as const) expect(hitActions(state, g, hit)).toEqual(['read', 'link']);
  const bare: DeepHit = { ...hit, entryUuid: null };
  expect(hitActions('live', g, bare)).toEqual(['read', 'go', 'link', 'scope']);
  expect(hitActions('live', g, { ...hit, entryUuid: 'u1', line: null })).toEqual(['go', 'branch', 'bookmark', 'scope']);
  expect(hitActions('none', groupOf(), { ...hit, bookmark: { id: 1, label: '', at: 't' } })).toEqual(['read', 'link', 'closest']);
  expect(splitActions(['read', 'go', 'branch', 'link', 'bookmark', 'scope'])).toEqual({ strip: ['read', 'go', 'link'], menu: ['branch', 'bookmark', 'scope'] });
  expect(splitActions(['read', 'link', 'closest'])).toEqual({ strip: ['read', 'link'], menu: ['closest'] });
});

test('the layout is remembered per device: default ledger, a stored pick wins, a blocked store never throws', () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } };
  expect(DEFAULT_LAYOUT).toBe('ledger');
  expect(readLayout(storage)).toBe('ledger');
  writeLayout('best', storage);
  expect(store.get(LAYOUT_KEY)).toBe('best');
  expect(readLayout(storage)).toBe('best');
  store.set(LAYOUT_KEY, 'something else');
  expect(readLayout(storage)).toBe('ledger');
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  expect(readLayout(blocked)).toBe('ledger');
  expect(() => writeLayout('best', blocked)).not.toThrow();
  expect(readLayout(null)).toBe('ledger');
});
