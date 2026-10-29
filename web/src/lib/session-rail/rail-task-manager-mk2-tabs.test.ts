/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';
import { fakeActive } from './test-support.svelte';

const mk = (id: number, status: string): unknown => ({
  id, list: '1', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: status === 'question' ? 'question' : '', revision: 1, created_seq: id, seq: id,
  deleted: false, status, title: null,
  thread: [{ id: 10 + id, item_id: id, author: 'claude', kind: status === 'question' ? 'question' : 'reply', text: `line ${id}`, answered: false, created_at: 1000 + id, seq: id }],
});
const ITEMS = [mk(1, 'question'), mk(2, 'review'), mk(3, 'working'), mk(4, 'open'), mk(5, 'open')];
(ITEMS[0] as { unread?: boolean }).unread = true;
(ITEMS[2] as { unread?: boolean }).unread = true;
(ITEMS[4] as { unread?: boolean; status: string }).unread = true;
(ITEMS[4] as { status: string }).status = 'done';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../item-settings/store.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../item-settings/store.svelte')>()),
  widgetSetting: () => true,
  isWidgetDisabled: () => false,
}));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return {
    ...real,
    authFetch: async (full: string) => {
      // the live read adds a query string (live_only, hide_completed), so the path is matched without it
      const path = full.split('?')[0];
      if (path === '/cplugs/huddle/aggregate') return { cursor: 5, groups: [{ list: '1', name: 'p', project_id: 1, revision: 1, items: ITEMS }] };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '1', name: 'p', project_id: 1, items: 5, open: 5, review: 1, questions: 1, claude_seq: 5 }] };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/swarm/roster') return { agents: [] };
      return { revision: 1, settings: {} };
    },
  };
});
vi.mock('../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import { RAIL_FIELD } from './rail-model';
import { follow, keyIn, mountRails, unmountRails } from './rail-test-harness';
import { huddle } from '../../cplugs/huddle/huddle.svelte';
import { taskManagerPrefs } from '../../cplugs/huddle/task-manager-prefs.svelte';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import './alert-count-sources.svelte';

setLocale('en');
installPopoverPolyfill();

async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

beforeEach(() => {
  fakeActive.id = 'ses_1';
  mountRails();
});
afterEach(() => {
  unmountRails();
  document.body.innerHTML = '';
  huddle.openId = null as never;
});

describe('TM Mark II hosted by the session rail, view all', () => {
  test('an opened task draws the Mark II task tab strip inside the rail copy', async () => {
    follow(RAIL_FIELD, { v: 2, sections: [{ items: [{ widget: 'core.task-manager-mk2', view: 'all' }] }] });
    keyIn('side', 'core.task-manager-mk2').click();
    await settle();
    const rail = document.querySelector<HTMLElement>('[data-rail-out-widget]')!;
    expect(rail).not.toBeNull();
    taskManagerPrefs.accordion = true; huddle.openId = 1 as never;
    await settle();
    expect(rail.querySelector('[data-task-manager-detail="1"]')).not.toBeNull();
    expect(rail.querySelector('[data-task-manager-mk2-tabs="1"] [role="tablist"]')).not.toBeNull();
  });

  test('the title strip carries `n unread`, the number the unread chip shows, and nothing at zero (issue #1710)', async () => {
    follow(RAIL_FIELD, { v: 2, sections: [{ items: [{ widget: 'core.task-manager-mk2', view: 'all', options: { show_header: true } }] }] });
    keyIn('side', 'core.task-manager-mk2').click();
    await settle();
    const rail = document.querySelector<HTMLElement>('[data-rail-out-widget]')!;
    const chip = rail.querySelector<HTMLElement>('[data-task-manager-mk2-chip="unread"] .mk2-chip-count')!;
    const chipN = chip.textContent!.match(/\d+/)![0];
    expect(chipN).toBe('2');
    const head = rail.querySelector<HTMLElement>('[data-mk2-head-count="unread"]')!;
    expect(head.querySelector('.mk2-head-ico svg')).not.toBeNull();
    expect(head.querySelector('.mk2-head-num')?.textContent?.trim()).toBe(chipN);
    expect(head.querySelector('.mk2-head-words')?.textContent?.trim()).toBe(`${chipN} unread`);
    const needsChipN = rail.querySelector<HTMLElement>('[data-task-manager-mk2-chip="needs_you"] .mk2-chip-count')!.textContent!.match(/\d+/)![0];
    expect(rail.querySelector('[data-mk2-head-count="needs-you"] .mk2-head-num')?.textContent?.trim()).toBe(needsChipN);
    huddle.groups = huddle.groups!.map((g) => ({ ...g, items: g.items.map((it) => ({ ...it, unread: false, info_unread: 0 })) }));
    await settle();
    expect(rail.querySelector('[data-mk2-head-count="unread"]')).toBeNull();
  });
});
