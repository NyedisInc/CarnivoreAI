/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import RailKeyMenu from '../widget-menu/RailKeyMenu.svelte';
import { fakeActive } from './test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { ...(await importOriginal<Record<string, unknown>>()), entryFor: () => ({ component: ScopeProbe }) };
});

import { BOTTOM_FIELD, follow, keyIn, keysIn, mountRails, unmountRails, written } from './rail-test-harness';
import { RAIL_FIELD } from './rail-model';
import { editorSeams, layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { homeLayout } from '../../opscenter/engine/layout.svelte';
import { widgetBars } from '../widget-bars/bar-settings.svelte';
import { emptyMenu, emptyMenuNodes } from '../../opscenter/layout-editor/empty-space-menu.svelte';
import { registerDraftWidget, type DraftSpec } from '../../widget-harness/draft-register';
import { declareWidgetActions } from '../../opscenter/widgets/menu/declared-actions.svelte';
import { railBodyKey } from './rail-body-key';

// jsdom has no popover API; the cascade menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const one = (...items: Record<string, unknown>[]) => ({ v: 2, sections: [{ items }] });
const nodes = (): (string | undefined)[] => [...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset['node']);
const at = (id: string): HTMLElement => document.querySelector<HTMLElement>(`[data-node="${id}"]`)!;

function rightClick(el: HTMLElement): MouseEvent {
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  el.dispatchEvent(event);
  flushSync();
  return event;
}

const realSeams = { ...editorSeams };

let barWrites: unknown[] = [];

function watchBarWrites(): void {
  barWrites = [];
  const bridge = (globalThis as unknown as { PreferenceBridge: { write: (field: string, value: unknown, ...rest: unknown[]) => Promise<unknown> } }).PreferenceBridge;
  const rest = bridge.write;
  bridge.write = async (field, value, ...more) => {
    if (field !== 'widget_bars') return rest(field, value, ...more);
    barWrites.push(value);
    return { status: 'committed' };
  };
  widgetBars.reload();
}

beforeEach(() => {
  fakeActive.id = 'ses_1';
  layoutEditor.active = false;
  editorSeams.page = () => 'home';
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => true;
  mountRails();
  watchBarWrites();
});
afterEach(() => {
  Object.assign(editorSeams, realSeams);
  emptyMenu.at = null;
  unmountRails();
  vi.restoreAllMocks();
});

describe('the bar sizes are in the bar\'s own menu only (tweak 8c8a373ef: they leave every widget menu)', () => {
  test('a key menu on either bar offers no size radio', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }, { widget: 'core.notes' }));
    rightClick(keyIn('side', 'core.files'));
    expect(nodes().filter((id) => /^bar-size-/.test(id ?? ''))).toEqual([]);
    expect(nodes()).toEqual(expect.arrayContaining(['pop-out', 'close-widget']));
  });

  test('the bottom bar\'s own menu writes the bottom bar\'s leaf', async () => {
    emptyMenu.target = 'bottom';
    emptyMenuNodes().find((n) => n.id === 'bar-size-compact')!.run!();
    await vi.waitFor(() => expect(barWrites.at(-1)).toEqual({ v: 1, bottom: { size: 'compact' } }));
  });
});

describe('every key opens the menu, in either mode', () => {
  test('normal mode: pop out and show header and close, no pin and no lock item; Shift+F10 opens it from the keyboard', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }));
    const key = keyIn('side', 'core.files');
    key.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
    flushSync();
    expect(nodes()).toEqual(expect.arrayContaining(['pop-out', 'show-header', 'close-widget']));
    expect(nodes().filter((id) => /pin|lock/.test(id ?? ''))).toEqual([]);
  });

  test('pop out opens that widget in its own window', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: () => {} } as unknown as Window);
    follow(RAIL_FIELD, one({ widget: 'core.files' }));
    rightClick(keyIn('side', 'core.files'));
    at('pop-out').click();
    flushSync();
    expect(String(open.mock.calls[0]?.[0])).toContain('widget=core.files');
    expect(document.querySelector('.acm-menu')).toBeNull();
  });

  test('close widget takes the key out of the bar', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }, { widget: 'core.notes' }));
    rightClick(keyIn('side', 'core.files'));
    at('close-widget').click();
    flushSync();
    expect(keysIn('side')).toEqual(['core.notes']);
  });

  test('edit layout: move up and down step inside the section, and move to the bottom bar carries the key across', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }, { widget: 'core.notes' }));
    layoutEditor.active = true;
    flushSync();
    rightClick(keyIn('side', 'core.files'));
    expect(at('widget-move-up').getAttribute('aria-disabled')).toBe('true');
    expect(at('move-to-bar').textContent).toContain('move to the bottom bar');
    at('widget-move-down').click();
    flushSync();
    expect(keysIn('side')).toEqual(['core.notes', 'core.files']);
    rightClick(keyIn('side', 'core.files'));
    at('move-to-bar').click();
    flushSync();
    expect(keysIn('side')).toEqual(['core.notes']);
    expect(keysIn('bottom')).toContain('core.files');
  });
});

describe('one menu at a time on the bar', () => {
  test('a second right-click on another key replaces the open menu, never stacks one', () => {
    follow(RAIL_FIELD, one({ widget: 'core.files' }, { widget: 'core.notes' }));
    rightClick(keyIn('side', 'core.files'));
    rightClick(keyIn('side', 'core.notes'));
    expect(document.querySelectorAll('.acm-menu')).toHaveLength(1);
  });
});

describe('the bar\'s own menu (empty space, handle, edge)', () => {
  test('size radios write the size leaf; pin bar writes the mode leaf', async () => {
    emptyMenu.target = 'side';
    const menu = emptyMenuNodes();
    expect(menu.map((n) => n.id)).toEqual(['bar-size-compact', 'bar-size-cozy', 'bar-size-detailed', 'pin-bar', 'edit-layout']);
    menu.find((n) => n.id === 'bar-size-compact')!.run!();
    await vi.waitFor(() => expect(barWrites.at(-1)).toEqual({ v: 1, side: { size: 'compact' } }));
    emptyMenuNodes().find((n) => n.id === 'pin-bar')!.run!();
    await vi.waitFor(() => expect(barWrites.at(-1)).toEqual({ v: 1, side: { size: 'compact', mode: 'autohide' } })  );
  });
});

describe('closing the key menu reads no torn-down state (#1785)', () => {
  test('a press outside closes the menu (pointer, Escape, focus) with no error from the anchor prop reading the cleared key menu', () => {
    const errors: unknown[] = [];
    const onError = (event: ErrorEvent): void => {
      errors.push(event.error);
      event.preventDefault();
    };
    window.addEventListener('error', onError);
    try {
      follow(RAIL_FIELD, one({ widget: 'core.files' }, { widget: 'core.notes' }));
      rightClick(keyIn('side', 'core.files'));
      expect(document.querySelector('.acm-menu')).not.toBeNull();
      for (const close of [
        () => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })),
        () => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })),
        () => document.body.dispatchEvent(new FocusEvent('focusin', { bubbles: true })),
      ]) {
        rightClick(keyIn('side', 'core.files'));
        close();
        flushSync();
      }
      expect(document.querySelector('.acm-menu')).toBeNull();
    } finally {
      window.removeEventListener('error', onError);
    }
    expect(errors).toEqual([]);
  });
});

function registerProbe(): void {
  const spec: DraftSpec = {
    id: 'core.rail-probe', slot: 'rail-probe', title: 'Rail probe', instancing: 'singleton', hosts: ['home', 'terminal'],
    category: 'monitoring', type: 'list', capabilities: [], fits: { sizes: ['small', 'wide'], anySize: true, max_per_surface: 1 },
    cell: { icon: 'grid', iconTone: 'cyan', minPx: 220, minHeight: 88, widthStates: [{ name: 'name', min: 220 }], heightStates: [{ name: 'title', min: 0 }, { name: 'rows', min: 88 }] } as DraftSpec['cell'],
  };
  registerDraftWidget({ spec, component: (() => undefined) as never, fixtures: { data: {}, empty: {} } as never });
}

describe('a Widget Lab draft\'s rail key works like a shipped widget\'s (widget spec section 11 rule 5)', () => {
  test('its key is drawn on the rail and a click opens its slide-out', () => {
    registerProbe();
    follow(RAIL_FIELD, one({ widget: 'core.rail-probe' }));
    keyIn('side', 'core.rail-probe').click();
    flushSync();
    expect(document.querySelector('[data-rail-slideout="core.rail-probe"]')).not.toBeNull();
  });

  test('the key menu of a registered non-core manifest shows its declared actions and the standard items', () => {
    registerProbe();
    const withdraw = declareWidgetActions(railBodyKey({ id: 'core.rail-probe' }, null, null), 'probe', [{ id: 'probe-refresh', label: 'refresh probe', run: () => {} }]);
    follow(RAIL_FIELD, one({ widget: 'core.rail-probe' }));
    const menu = mount(RailKeyMenu, { target: document.body, props: { edge: 'side', itemKey: 'core.rail-probe', anchor: document.body, onClose: () => {} } });
    flushSync();
    expect(nodes()).toEqual(expect.arrayContaining(['probe-refresh', 'close-widget']));
    unmount(menu);
    withdraw();
  });
});
