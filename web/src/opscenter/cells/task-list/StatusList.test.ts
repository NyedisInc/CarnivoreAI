/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const ITEMS = [
  { id: 6, list: '1', text: 'scheduled one', note: '', position: 6, created_by: 'claude', state: 'open', kind: '', revision: 1, created_seq: 6, seq: 6, deleted: false, status: 'scheduled', title: null,
    thread: [{ id: 16, item_id: 6, author: 'claude', kind: 'reply', text: 'latest on 6', answered: false, created_at: 1_006, seq: 6 }] },
];

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 6, groups: [{ list: '1', name: 'p', project_id: 1, revision: 1, items: ITEMS }] };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '1', name: 'p', project_id: 1, items: 1, open: 1, review: 0, questions: 0, claude_seq: 6 }] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null, ok: true };
      return {};
    },
  };
});
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import StatusList from './StatusList.svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';

setLocale('en');
cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the status modal list', () => {
  test('lists a scheduled row and draws no automations key on it', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(StatusList, { target: host, props: { list: '1', kind: 'scheduled' } });
    for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    const rows = host.querySelectorAll<HTMLElement>('[data-task-manager-list-row]');
    expect(rows).toHaveLength(1);
    expect(rows[0]!.dataset['status']).toBe('scheduled');
    expect(host.querySelector('[data-huddle-list-automations]')).toBeNull();
  });
});
