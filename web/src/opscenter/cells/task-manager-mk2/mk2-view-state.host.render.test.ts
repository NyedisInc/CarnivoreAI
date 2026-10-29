/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 1 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: [mk(1, '7'), mk(5, '7', { title: 'ship it', unread: true })] }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: [mk(1, one[1] as string), mk(5, one[1] as string, { title: 'ship it', unread: true })] };
      return {};
    },
  };
});
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  sessions: { data: [{ session_row_id: 1, project_id: 7, session: { id: 'ses_1', working_dir: '/x' } }], status: 'ok' },
  primarySessionId: () => 'ses_1',
}));
vi.mock('../../lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import PlacementBody from '../../../lib/zone-shell/PlacementBody.svelte';
import { HOST_LOOKS } from '../../../lib/zone-shell/host-looks';
import { CORE_MANIFESTS } from '../../widgets/core-manifests';
import { sizes } from '../../engine/observe.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { resetInspections } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';

cplugEnablement.enabled = { huddle: true };
const SINGLE = CORE_MANIFESTS['core.task-manager-mk2']!;
const ALL = CORE_MANIFESTS['core.task-manager-mk2-all']!;
const apps: object[] = [];
const store = { setOption: vi.fn(), setView: vi.fn(), resetOptions: vi.fn(), remove: vi.fn(() => true) };

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  for (const m of [SINGLE, ALL]) sizes[HOST_LOOKS['rail'].keyFor(m, null, null)] = { width: 420, height: 600 };
});
afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
  try { localStorage.clear(); } catch { /* jsdom without storage */ }
});

async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function drawRail(...manifests: Array<typeof SINGLE>): Promise<HTMLElement[]> {
  const boxes = manifests.map((manifest) => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(PlacementBody, { target, props: { host: 'rail', source: store, manifest, options: {}, placementKey: manifest.id } as never }));
    return target;
  });
  await settle();
  return boxes;
}

/** Forget the in-memory side of the view, as a page reload does. */
function reload(): void {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
}

const pressed = (box: HTMLElement, chip: string): string | null => box.querySelector(`[data-task-manager-mk2-chip="${chip}"]`)?.getAttribute('aria-pressed') ?? null;

describe('TM Mark II chip through the real host path', () => {
  test('the picked chip is still picked after a reload', async () => {
    const [box] = await drawRail(SINGLE);
    (box!.querySelector('[data-task-manager-mk2-chip="unread"]') as HTMLButtonElement).click();
    await settle();
    expect(pressed(box!, 'unread')).toBe('true');

    reload();
    const [again] = await drawRail(SINGLE);
    expect(pressed(again!, 'unread')).toBe('true');
  });

  test('a copy that never had a filter drawn beside it does not wipe the picked chip, on the page or after a reload', async () => {
    const [box] = await drawRail(SINGLE);
    (box!.querySelector('[data-task-manager-mk2-chip="unread"]') as HTMLButtonElement).click();
    await settle();
    expect(localStorage.getItem(`carnivore.core.task-manager-mk2-all.${HOST_LOOKS['rail'].keyFor(ALL, null, null)}.view`)).toBeNull();

    reload();
    const [again] = await drawRail(SINGLE, ALL);
    expect(pressed(again!, 'unread')).toBe('true');
    reload();
    const [last] = await drawRail(ALL, SINGLE);
    expect(pressed(last!, 'unread')).toBe('true');
    expect(JSON.parse(localStorage.getItem(`carnivore.core.task-manager-mk2.${HOST_LOOKS['rail'].keyFor(SINGLE, null, null)}.view`) as string).chip).toBe('unread');
  });
});
