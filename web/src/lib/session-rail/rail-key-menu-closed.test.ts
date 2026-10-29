/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { DECLARED_PROBE_ACTION, declaringLog, fakeActive } from './test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const { DeclaringProbe } = await import('./test-support.svelte');
  return { ...(await importOriginal<Record<string, unknown>>()), entryFor: () => ({ component: DeclaringProbe }) };
});

import { BOTTOM_FIELD, follow, keyIn, mountRails, unmountRails } from './rail-test-harness';
import { RAIL_FIELD } from './rail-model';
import { registerDraftWidget, type DraftSpec } from '../../widget-harness/draft-register';

// jsdom has no popover API; the cascade menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const one = (...items: Record<string, unknown>[]) => ({ v: 2, sections: [{ items }] });
const nodes = (): (string | undefined)[] => [...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset['node']);
const at = (id: string): HTMLElement => document.querySelector<HTMLElement>(`[data-node="${id}"]`)!;
const panelOf = (id: string): Element | null => document.querySelector(`[data-rail-slideout="${id}"]`);

function rightClick(el: HTMLElement): void {
  el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
}

beforeEach(() => {
  fakeActive.id = 'ses_1';
  Object.assign(declaringLog, { live: 0, made: 0, runs: [] });
  mountRails();
});
afterEach(() => {
  unmountRails();
  vi.restoreAllMocks();
});

describe('a closed key\'s menu holds its widget\'s declared actions', () => {
  test('a shipped widget: the declared action and the key items, with the panel still closed', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }));
    expect(panelOf('core.files')).toBeNull();
    rightClick(keyIn('side', 'core.files'));
    expect(nodes()).toEqual(expect.arrayContaining([DECLARED_PROBE_ACTION, 'pop-out', 'show-header', 'close-widget']));
    expect(panelOf('core.files')).toBeNull();
  });

  test('a Widget Lab draft: the same', () => {
    const spec: DraftSpec = {
      id: 'core.closed-probe', slot: 'closed-probe', title: 'Closed probe', instancing: 'singleton', hosts: ['home', 'terminal'],
      category: 'monitoring', type: 'list', capabilities: [], fits: { sizes: ['small', 'wide'], anySize: true, max_per_surface: 1 },
      cell: { icon: 'grid', iconTone: 'cyan', minPx: 220, minHeight: 88, widthStates: [{ name: 'name', min: 220 }], heightStates: [{ name: 'title', min: 0 }, { name: 'rows', min: 88 }] } as DraftSpec['cell'],
    };
    registerDraftWidget({ spec, component: (() => undefined) as never, fixtures: { data: {}, empty: {} } as never });
    follow(RAIL_FIELD, one({ widget: 'core.closed-probe' }));
    rightClick(keyIn('side', 'core.closed-probe'));
    expect(nodes()).toEqual(expect.arrayContaining([DECLARED_PROBE_ACTION, 'close-widget']));
  });

  test('the unseen copy lives only while the menu is open', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }));
    rightClick(keyIn('side', 'core.files'));
    expect(declaringLog.live).toBe(1);
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(document.querySelector('.acm-menu')).toBeNull();
    expect(declaringLog.live).toBe(0);
  });

  test('choosing a declared action opens the panel and runs it on the copy drawn there, not the unseen one', async () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }));
    rightClick(keyIn('side', 'core.files'));
    const unseen = declaringLog.made;
    at(DECLARED_PROBE_ACTION).click();
    flushSync();
    await vi.waitFor(() => expect(declaringLog.runs).toHaveLength(1));
    expect(panelOf('core.files')).not.toBeNull();
    expect(declaringLog.runs[0]).not.toBe(unseen);
    expect(declaringLog.live).toBe(1);
  });

  test('an open panel\'s key menu reads the drawn copy and mounts no second one', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }));
    keyIn('side', 'core.files').click();
    flushSync();
    expect(panelOf('core.files')).not.toBeNull();
    expect(declaringLog.live).toBe(1);
    rightClick(keyIn('side', 'core.files'));
    expect(nodes()).toContain(DECLARED_PROBE_ACTION);
    expect(declaringLog.live).toBe(1);
    at(DECLARED_PROBE_ACTION).click();
    flushSync();
    expect(declaringLog.runs).toEqual([1]);
  });
});

describe('a widget that owns a live pane is never mounted unseen', () => {
  test('the companion shell (terminal input): its closed key menu mounts nothing and still opens with the key items', () => {
    follow(BOTTOM_FIELD, one({ widget: 'core.shell' }));
    rightClick(keyIn('bottom', 'core.shell'));
    expect(declaringLog.made).toBe(0);
    expect(nodes()).toEqual(expect.arrayContaining(['close-widget']));
    expect(nodes()).not.toContain(DECLARED_PROBE_ACTION);
  });
});
