/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';


// The "more" menu is the engine's manual popover; jsdom has no popover API.
(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const wire = vi.hoisted(() => ({
  live: {} as Record<string, unknown>,
  calls: [] as string[],
  openedSession: [] as string[],
  exported: {} as Record<string, unknown>,
  onPush: null as null | ((topics: string[]) => void),
}));

vi.mock('../../cplugs/sdk/sessions.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../cplugs/sdk/sessions.svelte')>()),
  sessionRowForConversation: (id: string) => wire.live[id],
  resourcePush: () => ({ onChange: (fn: (topics: string[]) => void) => { wire.onPush = fn; return () => { wire.onPush = null; }; } }),
  openSession: async (id: string) => { wire.openedSession.push(id); return true; },
}));
vi.mock('../resource-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../resource-push/boot')>()),
  resourcePush: () => ({ onChange: (fn: (topics: string[]) => void) => { wire.onPush = fn; return () => { wire.onPush = null; }; } }),
}));

vi.mock('./result-actions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./result-actions')>()),
  resumeSession: async (uuid: string) => { wire.calls.push(`resume ${uuid}`); },
  branchAt: async (s: string, e: string, c: string) => { wire.calls.push(`branch ${s} ${e} ${c}`); return { sessionId: 'ses_b', tmuxName: 'carnivore_b' }; },
  bookmarkAt: async (s: string, e: string) => { wire.calls.push(`bookmark ${s} ${e}`); },
  copyText: async (text: string) => { wire.calls.push(`copy ${text}`); return true; },
}));

const { default: DeepSearchResults } = await import('./DeepSearchResults.svelte');
const { DeepSearchController } = await import('./deepsearch.svelte');
const { readAnswer } = await import('./deepsearch-api');
const { LAYOUT_KEY } = await import('./result-model');

const settle = async (): Promise<void> => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
  flushSync();
};

const hit = (line: number, extra: Record<string, unknown> = {}) => ({
  line, kind: line % 2 ? 'assistant' : 'user', snippet: `we \u0002restic\u0003 ${line}`, file_kind: 'conversation', at: '2026-10-15T08:31:00', entry_uuid: `u-${line}`, ...extra,
});

const ANSWER = () => ({
  query: 'restic', total_conversations: 4, total_matches: 12, stale: ['gone-1'],
  groups: ([
    { conversation_id: 'conv-live', matches: 5, session_uuid: 's-live', session: 'nightly restic fix', project: 'backup-tools', last_active: '2026-10-15T10:00:00', hits: [hit(1), hit(2), hit(3)] },
    { conversation_id: 'conv-asleep', matches: 2, session_uuid: 's-asleep', session: null, first_prompt: 'move the restic repo password\nout of the env file', also_on: ['mini'], last_active: '2026-10-14T10:00:00', hits: [hit(4), hit(5)] },
    { conversation_id: 'conv-backup', matches: 1, session_uuid: null, session: null, first_prompt: null, working_dir: '/Users/x/backup-tools', last_active: '2026-10-02T10:00:00', hits: [hit(6, { from_backup: true })] },
    { conversation_id: 'conv-none', matches: 1, session_uuid: null, session: null, first_prompt: null, working_dir: null, hits: [hit(7, { file_kind: 'subagent' })] },
  ] as Array<Record<string, unknown>>).map((g) => ({ ...g, exported: wire.exported[g.conversation_id as string] })),
  ingest: { state: 'running' },
});

let host: HTMLElement;
let mounted: Record<string, unknown> | null = null;
let searches: Array<{ q: string; scope: unknown }> = [];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-15T12:00:00'));
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
  wire.live = { 'conv-live': { activity_status: 'working', label: 'nightly restic fix' } };
  wire.calls = [];
  wire.openedSession = [];
  wire.exported = {};
  wire.onPush = null;
  searches = [];
});

afterEach(() => {
  if (mounted) unmount(mounted);
  mounted = null;
  host.remove();
  vi.useRealTimers();
});

async function paint() {
  const opened: unknown[] = [];
  const shown: unknown[] = [];
  const api = {
    filters: true,
    search: async (q: string, _offset: number, _signal: AbortSignal, scope?: { conversationId?: string; kinds?: string }) => {
      searches.push({ q, scope });
      if (scope?.conversationId === 'conv-live') {
        return readAnswer({ ...ANSWER(), total_conversations: 1, groups: [{ ...ANSWER().groups[0], hits: [hit(1), hit(2), hit(3), hit(8), hit(9)] }] });
      }
      return readAnswer(ANSWER());
    },
  };
  const controller = new DeepSearchController(api, async (t) => { opened.push(t); return 'switched'; }, undefined, (s) => { shown.push(s); });
  controller.showActions = true; // the context mode draws the buttons
  await controller.run('restic', 0);
  controller.move(1);  // nothing is picked until an arrow or a click; these tests read the first hit picked
  mounted = mount(DeepSearchResults, { target: host, props: { controller } });
  await settle();
  return { controller, opened, shown };
}

const text = (el: Element | null): string => el?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
const click = async (el: Element | null): Promise<void> => { (el as HTMLElement).click(); await settle(); };
const rightClick = async (el: Element | null): Promise<void> => { el!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 40 })); await settle(); };
const actionsOf = (row: Element | null): string[] => [...row!.querySelectorAll('[data-testid="deepsearch-actions"] [data-action]')].map((b) => b.getAttribute('data-action')!);
const namesShown = (): string[] => [...new Set([...host.querySelectorAll('.dps__hit .sd-hit__name')].map((n) => text(n)))];
const hitsOf = (n: number): HTMLElement[] => {
  const name = namesShown()[n]!;
  return ([...host.querySelectorAll('.dps__hit')] as HTMLElement[]).filter((row) => text(row.querySelector('.sd-hit__name')) === name);
};

test('A, the ledger, is the default: an honest count, one stale line, names by the ladder and a state per conversation', async () => {
  await paint();
  expect(host.querySelector('[data-layout="ledger"].dps__list')).not.toBeNull();
  expect(text(host.querySelector('.dps__status'))).toBe('12 hits in 4 conversations');
  expect(text(host.querySelector('[data-testid="deepsearch-stale"]'))).toBe('1 conversation changed since it was indexed; its hits are hidden until it is read again');
  expect(host.querySelector('.dps__cap')).toBeNull();
  expect(namesShown()).toEqual(['nightly restic fix', 'move the restic repo password out of the env file', 'backup-tools', 'untitled conversation']);
  expect([0, 1, 2, 3].map((n) => hitsOf(n)[0]!.getAttribute('title'))).toEqual([
    'backup-tools · live · 5 hits', 'asleep · 2 hits', 'original deleted · 1 hit', 'never opened here · 1 hit',
  ]);
  for (let n = 0; n < 4; n++) {
    const kids = [...hitsOf(n)[0]!.querySelector('.sd-hit__top')!.children];
    expect(kids.findIndex((k) => k.classList.contains('sd-hit__name')), `conversation ${n}: a light before the name`).toBeGreaterThan(0);
  }
  expect(text(host.querySelector('[data-testid="deepsearch-from-backup"]'))).toBe('from backup');
  expect(host.querySelector('[data-testid="deepsearch-from-backup"]')!.getAttribute('title')).toBe('claude code deleted the original; this text is read from a conversation backup');
  expect(text(host.querySelector('[data-testid="deepsearch-host"]'))).toBe('also on mini');
  expect(text(host.querySelector('.dps__tag:not(.dps__host):not(.dps__tag--backup)'))).toBe('subagent');
});

test('A shows two hits a conversation, the match in the accent, and "N more" fetches the rest in place', async () => {
  const { controller } = await paint();
  const firstGroupHits = hitsOf(0);
  expect(firstGroupHits).toHaveLength(2);
  expect(firstGroupHits[0]!.querySelector('mark.sd-mark')!.textContent).toBe('restic');
  const row = firstGroupHits[0]!;
  const snip = row.querySelector(':scope > .sd-hit__snip')!;
  const top = row.querySelector(':scope > .sd-hit__top')!;
  expect(snip.querySelector('mark.sd-mark')).not.toBeNull();
  expect(top.contains(snip)).toBe(false);
  expect(text(top.querySelector('.sd-r__meta'))).toMatch(/^agent \S+/);
  expect(row.querySelector(':scope > [data-testid="deepsearch-actions"]')).not.toBeNull();
  expect(snip.compareDocumentPosition(row.querySelector(':scope > [data-testid="deepsearch-actions"]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(row.querySelector('[data-action="read"]')!.getAttribute('data-btn')).toBe('confirm');
  expect(row.querySelector('[data-action="go"]')!.getAttribute('data-btn')).toBe('secondary');
  expect(fs.readFileSync(path.resolve(process.cwd(), 'src/lib/deepsearch/search-d.css'), 'utf8')).toMatch(/\.sd-acts \[data-btn='confirm'\] \{[^}]*--_btn-edge: var\(--oc-green\);[^}]*--_btn-ink: var\(--oc-green\);/);
  const more = host.querySelector('[data-testid="deepsearch-more-in"]')!;
  expect(text(more)).toBe('3 more in this conversation');
  await click(more);
  expect(searches.at(-1)).toMatchObject({ scope: { conversationId: 'conv-live' } });
  expect(hitsOf(0)).toHaveLength(5);
  expect(host.querySelector('[data-testid="deepsearch-more-in"]')).toBeNull();
  expect(controller.groups.map((g) => g.conversationId)).toEqual(['conv-live', 'conv-asleep', 'conv-backup', 'conv-none']);
});

test('every hit shows the buttons its state allows at rest, and the label says go or resume', async () => {
  await paint();
  expect(actionsOf(hitsOf(0)[0]!)).toEqual(['read', 'go', 'link', 'more']);
  expect(host.querySelector('[data-action="go"]')!.getAttribute('aria-label')).toBe('go to session');
  expect(actionsOf(hitsOf(1)[0]!)).toEqual(['read', 'resume', 'link', 'more']);
  expect(host.querySelector('[data-action="resume"]')!.getAttribute('aria-label')).toBe('resume');
  expect(actionsOf(hitsOf(2)[0]!), 'a copy read from a backup reads and links only').toEqual(['read', 'link']);
  expect(actionsOf(hitsOf(3)[0]!), 'no session: the same').toEqual(['read', 'link']);
  await click(hitsOf(1)[0]!);
  expect(actionsOf(hitsOf(1)[0]!)).toEqual(['read', 'resume', 'link', 'more']);
});

test('each button reaches its documented route', async () => {
  const { controller, opened, shown } = await paint();
  await click(host.querySelector('[data-action="go"]'));
  expect(opened).toMatchObject([{ conversationId: 'conv-live' }]);
  expect(wire.calls).toEqual([]);

  await rightClick(host.querySelector('.dps__hit'));
  await click(document.querySelector('[role="menu"] [data-node="branch"]'));
  expect(wire.calls).toEqual(['branch s-live u-1 conv-live']);
  expect(wire.openedSession).toEqual(['ses_b']);

  await click(host.querySelector('[data-action="link"]'));
  expect(wire.calls.at(-1)).toMatch(/^copy .*#deepsearch\/context\?c=conv-live&l=1$/);
  expect(text(host.querySelector('[data-testid="deepsearch-action-note"]'))).toBe('link copied');

  await rightClick(host.querySelector('.dps__hit'));
  await click(document.querySelector('[role="menu"] [data-node="bookmark"]'));
  expect(wire.calls.at(-1)).toBe('bookmark s-live u-1');

  await click(host.querySelector('[data-action="read"]'));
  expect(shown).toMatchObject([{ focus: 'hit', request: { conversationId: 'conv-live', line: 1 } }]);

  controller.active = 2;
  flushSync();
  await click(host.querySelector('[data-action="resume"]'));
  expect(wire.calls.at(-1)).toBe('resume s-asleep');
  expect(opened).toMatchObject([{ conversationId: 'conv-live' }, { conversationId: 'conv-asleep' }]);
});

test('B, best hits first: no caption, one block per hit, one-line hits, the chips ask the route for a kind', async () => {
  const { controller } = await paint();
  await click(host.querySelector('[data-layout="best"]'));
  expect(controller.layout).toBe('best');
  expect(localStorage.getItem(LAYOUT_KEY)).toBe('best');
  expect(host.querySelector('[data-layout="best"].dps__list')).not.toBeNull();
  expect(host.querySelector('.dps__cap')).toBeNull();
  expect(namesShown()).toHaveLength(4);
  expect(host.querySelectorAll('.dps__hit').length).toBe(2 + 2 + 1 + 1);
  expect(text(host.querySelector('.dps__hit .sd-hit__name'))).toBe('nightly restic fix');
  expect(text(host.querySelector('.dps__hit .sd-r__meta'))).toBe('agent, 3h ago');
  expect([...host.querySelectorAll('[data-testid="deepsearch-chips"] [data-kind]')].map((c) => c.textContent)).toEqual(['all', 'you', 'agent', 'tool']);
  expect(actionsOf(host.querySelector('.dps__hit'))).toEqual(['read', 'go', 'link', 'more']);
  await rightClick(host.querySelector('.dps__hit'));
  expect([...document.querySelectorAll('[role="menu"] [data-node]')].map((b) => b.getAttribute('data-node'))).toEqual(['read', 'go', 'branch', 'link', 'bookmark', 'scope']);

  await click(host.querySelector('[data-testid="deepsearch-chips"] [data-kind="user"]'));
  expect(searches.at(-1)).toMatchObject({ q: 'restic', scope: { kinds: 'user' } });
  expect(host.querySelector('[data-testid="deepsearch-chips"] [data-kind="user"]')!.getAttribute('aria-pressed')).toBe('true');
  await click(host.querySelector('[data-testid="deepsearch-chips"] [data-kind="all"]'));
  expect(searches.at(-1)!.scope).toMatchObject({ kinds: undefined });
});

test('"only this conversation" narrows the search to it, shows all its hits and offers the way back', async () => {
  const { controller } = await paint();
  await click(host.querySelector('[data-layout="best"]'));
  await rightClick(host.querySelector('.dps__hit'));
  await click(document.querySelector('[role="menu"] [data-node="scope"]'));
  expect(searches.at(-1)).toMatchObject({ scope: { conversationId: 'conv-live' } });
  expect(text(host.querySelector('[data-testid="deepsearch-scope"]'))).toBe('only in nightly restic fix show all');
  expect(host.querySelectorAll('.dps__hit')).toHaveLength(5);
  expect(host.querySelector('[data-testid="deepsearch-chips"]'), 'chips wait for the way back').toBeNull();
  await click(host.querySelector('[data-testid="deepsearch-scope"] button'));
  expect(controller.scope).toBeNull();
  expect(searches.at(-1)!.scope).toMatchObject({ conversationId: undefined });
  expect(namesShown()).toHaveLength(4);
});

test('the layout toggle: lowercase labels, A checked by default, and the pick is remembered for the next mount', async () => {
  await paint();
  const items = [...host.querySelectorAll('[data-testid="deepsearch-layout"] [role="radio"]')];
  expect(items.map((i) => i.textContent)).toEqual(['ledger', 'best hits']);
  expect(items.map((i) => i.getAttribute('aria-checked'))).toEqual(['true', 'false']);
  await click(items[1]!);
  expect(items.map((i) => i.getAttribute('aria-checked'))).toEqual(['false', 'true']);
  unmount(mounted!);
  mounted = null;
  host.innerHTML = '';
  await paint();
  expect(host.querySelector('[data-layout="best"]')).not.toBeNull();
  localStorage.setItem(LAYOUT_KEY, 'nonsense');
  unmount(mounted!);
  mounted = null;
  host.innerHTML = '';
  await paint();
  expect(host.querySelector('[data-layout="ledger"]')).not.toBeNull();
});

test('a paired computer holds a conversation: its tag names the computer and only read and link are offered', async () => {
  const { controller } = await paint();
  controller.groups = [{ ...controller.groups[1]!, hostKey: 'peer-mini', hostLabel: 'mini', alsoOn: [] }];
  controller.active = 0;
  await settle();
  expect(text(host.querySelector('[data-testid="deepsearch-host"]'))).toBe('mini');
  expect(host.querySelector('.dps__hit')!.getAttribute('title')).toBe('on another computer · 2 hits');
  expect(actionsOf(host.querySelector('.dps__hit'))).toEqual(['read', 'link']);
});

test('an exported conversation says "exported, in bundle X": the label when it has one, else the id; the others say nothing', async () => {
  wire.exported = {
    'conv-live': { bundle_id: 'crate-20261017-a1', label: 'october', exported_at: '2026-10-17T00:00:00+00:00', local_removed: false },
    'conv-asleep': { bundle_id: 'crate-1', label: null, exported_at: '2026-10-17T00:00:00+00:00', local_removed: true },
  };
  await paint();
  const tags = [...host.querySelectorAll('[data-testid="deepsearch-exported"]')];
  expect(tags.map((n) => text(n))).toEqual(['exported, in bundle october', 'exported, in bundle crate-1']);
  expect(tags.map((n) => n.getAttribute('title'))).toEqual([
    'a full copy of this conversation is in that export bundle',
    'a full copy of this conversation is in that export bundle; the local data was removed',
  ]);
  expect(hitsOf(2)[0]!.querySelector('[data-testid="deepsearch-exported"]')).toBeNull();
  expect(wire.exported['conv-none']).toBeUndefined();
});

test('an exports push frame patches only the exported tags, with no new search of the screen and no timer', async () => {
  const { controller } = await paint();
  expect(host.querySelector('[data-testid="deepsearch-exported"]')).toBeNull();
  expect(wire.onPush).not.toBeNull();
  controller.active = 2;
  wire.exported = { 'conv-backup': { bundle_id: 'crate-9', label: null, exported_at: null, local_removed: false } };
  wire.onPush!(['layouts']);
  await settle();
  expect(host.querySelector('[data-testid="deepsearch-exported"]')).toBeNull();
  wire.onPush!(['exports']);
  await settle();
  expect(text(host.querySelector('[data-testid="deepsearch-exported"]'))).toBe('exported, in bundle crate-9');
  expect(controller.active).toBe(2);
  wire.exported = {};
  wire.onPush!(['exports']);
  await settle();
  expect(host.querySelector('[data-testid="deepsearch-exported"]')).toBeNull();
});
