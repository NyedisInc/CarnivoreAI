/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { canonicalDom } from '../sidebar-shell/legacy-fixture';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

vi.mock('../../cplugs/sdk/sessions.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../cplugs/sdk/sessions.svelte')>()),
  sessionRowForConversation: (id: string) => (id === 'conv-live' ? { activity_status: 'working', label: 'nightly rsync fix' } : undefined),
}));
vi.mock('../resource-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../resource-push/boot')>()),
  resourcePush: () => ({ onChange: () => () => {} }),
}));

const { default: DeepSearchResults } = await import('./DeepSearchResults.svelte');
const { DeepSearchController } = await import('./deepsearch.svelte');
const { readAnswer } = await import('./deepsearch-api');
const { LAYOUT_KEY } = await import('./result-model');

const settle = async (): Promise<void> => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
  flushSync();
};
const hit = (line: number) => ({
  line, kind: line % 2 ? 'assistant' : 'user', snippet: `we \u0002rsync\u0003 ${line}`, file_kind: 'conversation', at: '2026-10-15T08:31:00', entry_uuid: `u-${line}`,
});
const ANSWER = (groups: Array<Record<string, unknown>>) => ({ query: 'rsync', total_conversations: groups.length, total_matches: groups.length * 2, stale: [], groups, ingest: { state: 'running' } });
const GROUPS = [
  { conversation_id: 'conv-live', matches: 3, session_uuid: 's-live', session: 'nightly rsync fix', project: 'backup-tools', last_active: '2026-10-15T10:00:00', hits: [hit(1), hit(2)] },
  { conversation_id: 'conv-asleep', matches: 2, session_uuid: 's-asleep', session: null, first_prompt: 'move the rsync repo password', last_active: '2026-10-14T10:00:00', hits: [hit(3), hit(4)] },
];
const TERMS = [{ term: 'rsync', docs: 41 }, { term: 'rsyncprofile', docs: 6 }];

let host: HTMLElement;
let mounted: Record<string, unknown> | null = null;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-15T12:00:00'));
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
});
afterEach(() => {
  if (mounted) unmount(mounted);
  mounted = null;
  host.remove();
  vi.useRealTimers();
});

async function paint(layout: 'ledger' | 'best', groups: Array<Record<string, unknown>>, suggest: boolean): Promise<string> {
  localStorage.setItem(LAYOUT_KEY, layout);
  const api = {
    filters: true,
    search: async () => readAnswer(ANSWER(groups)),
    suggest: async () => TERMS,
  };
  const controller = new DeepSearchController(api, async () => 'switched', undefined, () => {});
  controller.showActions = true;
  controller.query = 'resti';
  if (suggest) {
    controller.onType();
    vi.useRealTimers();
    await new Promise((r) => setTimeout(r, 300));
  }
  await controller.run('rsync', 0);
  controller.move(1);
  mounted = mount(DeepSearchResults, { target: host, props: { controller } });
  await settle();
  const dom = canonicalDom(host);
  unmount(mounted);
  mounted = null;
  host.replaceChildren();
  return dom;
}

function undoDeclaredChanges(dom: string): string {
  return dom.replace(/ svelte-[a-z0-9]+/g, '');
}

test('the results draw the recorded DOM', async () => {
  const ledger = await paint('ledger', GROUPS, true);
  const best = await paint('best', GROUPS, false);
  const none = await paint('ledger', [], false);
  const dom = undoDeclaredChanges(['=== ledger, suggestions open', ledger, '=== best hits', best, '=== no matches', none].join('\n'));
  await expect(dom).toMatchFileSnapshot('./__goldens__/results-before-d.html');
});
