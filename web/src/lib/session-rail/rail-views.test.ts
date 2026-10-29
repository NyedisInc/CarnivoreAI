/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { fakeActive } from './test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD } from './rail-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { follow, keyIn, mountRails, unmountRails, written } from './rail-test-harness';

// jsdom has no popover API; the cascade menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

/** The stored v2 value of a one-section rail. */
const one = (...items: Record<string, unknown>[]) => ({ v: 2, sections: [{ items }] });

function rightClick(el: HTMLElement): MouseEvent {
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  el.dispatchEvent(event);
  flushSync();
  return event;
}

beforeEach(() => {
  fakeActive.id = 'ses_1';
  mountRails();
});
afterEach(() => unmountRails());

const nodes = (): (string | undefined)[] => [...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset['node']);

describe('the right-click view menu', () => {
  test('opens in edit layout on a widget with views with the placement\'s view checked, and replaces the browser menu', () => {
    follow(RAIL_FIELD, one({ widget: 'core.tasks' }));
    layoutEditor.active = true;
    flushSync();
    const event = rightClick(keyIn('side', 'core.tasks'));
    expect(event.defaultPrevented).toBe(true);
    const looks = ['session', 'all'].map((id) => document.querySelector<HTMLElement>(`[data-node="${id}"]`)!);
    expect(looks.map((item) => item.textContent)).toEqual([expect.stringContaining('selected session'), expect.stringContaining('all sessions')]);
    expect(looks.map((item) => item.getAttribute('role'))).toEqual(['menuitemradio', 'menuitemradio']);
    expect(looks.map((item) => item.getAttribute('aria-checked'))).toEqual(['true', 'false']);
  });

  test('a widget with one face opens the same menu (item 685, Q2 a): no looks, the rest of the list', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes' }));
    const event = rightClick(keyIn('side', 'core.notes'));
    expect(event.defaultPrevented).toBe(true);
    expect(nodes()).toEqual(expect.arrayContaining(['pop-out', 'show-header', 'close-widget']));
    expect(document.querySelector('[data-node="session"], [data-node="all"]')).toBeNull();
  });

  test('picking all sessions stores the view for that placement alone and closes the menu', () => {
    follow(RAIL_FIELD, one({ widget: 'core.tasks' }, { widget: 'core.bookmarks' }));
    layoutEditor.active = true;
    flushSync();
    rightClick(keyIn('side', 'core.tasks'));
    document.querySelector<HTMLElement>('[data-node="all"]')!.click();
    flushSync();
    expect(document.querySelector('.acm-menu')).toBeNull();
    const stored = written.at(-1)!;
    expect(stored.field).toBe(RAIL_FIELD);
    expect((stored.value as { sections: { items: unknown[] }[] }).sections[0]!.items).toEqual([{ widget: 'core.tasks', view: 'all' }, { widget: 'core.bookmarks' }]);
  });
});

describe('the drawn view', () => {
  test('the slide-out draws the view\'s cell: the selected session cell with a scope, the all sessions cell without', () => {
    follow(RAIL_FIELD, one({ widget: 'core.tasks' }));
    keyIn('side', 'core.tasks').click();
    flushSync();
    expect(document.querySelector('[data-rail-body]')!.getAttribute('data-rail-body')).toBe('core.tasks');
    expect(document.querySelector<HTMLElement>('[data-probe]')!.dataset['scope']).toBe('ses_1:4');

    follow(RAIL_FIELD, one({ widget: 'core.tasks', view: 'all' }));
    expect(document.querySelector('[data-rail-body]')!.getAttribute('data-rail-body')).toBe('core.tasks-all');
    expect(document.querySelector<HTMLElement>('[data-probe]')!.dataset['scope']).toBe('none');
  });

  test('the globe marks the all sessions view only', () => {
    follow(RAIL_FIELD, one({ widget: 'core.tasks' }, { widget: 'core.bookmarks', view: 'all' }));
    expect(keyIn('side', 'core.tasks').querySelector('[data-widget-globe]')).toBeNull();
    expect(keyIn('side', 'core.bookmarks').querySelector('[data-widget-globe]')).not.toBeNull();
  });

  test('a rail stored with an old all sessions id reads as the merged widget showing that view', () => {
    follow(RAIL_FIELD, one({ widget: 'core.task-manager-all' }));
    expect(keyIn('side', 'core.task-manager').querySelector('[data-widget-globe]')).not.toBeNull();
    expect(keyIn('side', 'core.task-manager-all')).toBeNull();
  });
});

describe('right-click on any key, in either mode', () => {
  test('normal mode: every key opens its menu; settings wait for edit layout (Q3 b), the session | all switch does not (item 1048)', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }, { widget: 'core.crosstalk' }, { widget: 'core.tasks' }));
    for (const id of ['core.files', 'core.crosstalk', 'core.tasks']) {
      expect(rightClick(keyIn('side', id)).defaultPrevented).toBe(true);
      const ids = nodes();
      expect(ids).toEqual(expect.arrayContaining(['pop-out', 'show-header', 'close-widget']));
      if (id === 'core.tasks') expect(ids).toEqual(expect.arrayContaining(['session', 'all']));
      else expect(ids).not.toEqual(expect.arrayContaining(['session']));
      expect(ids).not.toContain('settings');
      expect(ids).not.toContain('widget-move-up');
    }
  });

  test('edit layout: settings and arranging join the list, pop out leaves it, and edit layout reads done editing', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }, { widget: 'core.crosstalk' }));
    layoutEditor.active = true;
    flushSync();
    expect(rightClick(keyIn('side', 'core.files')).defaultPrevented).toBe(true);
    expect(nodes()).toEqual(expect.arrayContaining(['showGlobalFolder', 'topFolder', 'show-header', 'widget-move-up', 'widget-move-down', 'move-to-bar', 'done-editing', 'close-widget']));
    expect(nodes()).not.toContain('pop-out');
    expect(document.querySelector('[data-node="widget-move-up"]')!.getAttribute('aria-disabled')).toBe('true');
    expect(document.querySelector('[data-node="widget-move-down"]')!.getAttribute('aria-disabled')).toBeNull();
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    flushSync();
    expect(rightClick(keyIn('side', 'core.crosstalk')).defaultPrevented).toBe(true);
    expect(nodes()).not.toContain('settings');
    expect(nodes()).toContain('show-header');
  });
});

describe('edit layout', () => {
  test('chip: none in normal mode; views or settings in edit layout', () => {
    follow(RAIL_FIELD, one({ widget: 'core.tasks' }, { widget: 'core.files' }, { widget: 'core.crosstalk' }));
    const chip = (id: string) => keyIn('side', id).querySelector<HTMLElement>('[data-view-chip]');
    expect(chip('core.tasks')).toBeNull();
    expect(chip('core.files')).toBeNull();
    expect(chip('core.crosstalk')).toBeNull();
    layoutEditor.active = true;
    flushSync();
    expect(chip('core.tasks')?.classList.contains('vchip--quiet')).toBe(false);
    expect(chip('core.files')).not.toBeNull();
    expect(chip('core.crosstalk')).toBeNull();
  });

  test('a key tooltip has the name, the view or category, and the right-click hint (every key has a menu)', () => {
    follow(RAIL_FIELD, one({ widget: 'core.tasks', view: 'all' }, { widget: 'core.crosstalk' }));
    expect(keyIn('side', 'core.tasks').title.split('\n')).toHaveLength(3);
    expect(keyIn('side', 'core.tasks').title.split('\n')[1]).toBe('all sessions');
    expect(keyIn('side', 'core.crosstalk').title.split('\n').pop()).toBe('right-click for options');
    layoutEditor.active = true;
    flushSync();
    expect(keyIn('side', 'core.crosstalk').title.split('\n').pop()).toBe('right-click for options');
  });
});
