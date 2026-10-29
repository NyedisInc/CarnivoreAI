/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { default: HeadBarProbe } = await import('../../opscenter/shell/fixtures/HeadBarProbe.svelte');
  return { entryFor: () => ({ component: HeadBarProbe }) };
});

import { RAIL_FIELD } from './rail-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { railSlideout } from './slideout.svelte';
import { railStores } from './rail-store.svelte';
import { follow, keyIn, mountRails, unmountRails, written } from './rail-test-harness';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
installPopoverPolyfill();

/** The stored v2 value of a one-section rail. */
const one = (...items: Record<string, unknown>[]) => ({ v: 2, sections: [{ items }] });

const section = (): HTMLElement => document.querySelector<HTMLElement>('[data-rail-out-widget="core.notes"]')!;

function openNotes(): void {
  keyIn('side', 'core.notes').click();
  flushSync();
}

beforeEach(() => mountRails());
afterEach(() => unmountRails());

describe('a rail section header', () => {
  test('is off by default: no header at all, so the bar and name of the cell are drawn nowhere (menu only)', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes' }));
    openNotes();
    expect(section()).not.toBeNull();
    expect(section().querySelector('[data-widget-head]')).toBeNull();
    expect(section().querySelector('[data-corner]')).toBeNull();
    expect(section().querySelector('[data-probe-bar]'), 'no head-handed control is drawn in the body either').toBeNull();
    expect(section().querySelector('[data-probe-name]'), 'no name text where the header was').toBeNull();
  });

  test('the key\'s edit layout menu ticks it on for that copy', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes' }));
    layoutEditor.active = true;
    flushSync();
    keyIn('side', 'core.notes').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
    flushSync();
    const tick = [...document.querySelectorAll<HTMLElement>('[role^="menuitem"]')].find((item) => item.textContent?.trim().startsWith('show header'))!;
    expect(tick.getAttribute('aria-checked')).toBe('false');
    tick.click();
    flushSync();
    expect(railStores.side.layout.sections[0]![0]!.options).toEqual({ show_header: true });
    expect(JSON.stringify(written.at(-1)!.value)).toContain('"show_header":true');
  });

  test('ticked on, the section wears the header, its bar goes up, and the x takes the copy out of the bar at once', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes', options: { show_header: true } }, { widget: 'core.files' }));
    openNotes();
    const head = section().querySelector('[data-widget-head]')!;
    expect(head).not.toBeNull();
    const parts = [...head.querySelectorAll('[data-corner], .oc-frame-name, [data-probe-bar], .oc-head-sep, [data-zone-popout], [data-head-close]')]
      .map((el) => (el.matches('[data-corner]') ? 'icon' : el.matches('.oc-frame-name') ? 'name' : el.matches('[data-probe-bar]') ? 'bar' : el.matches('.oc-head-sep') ? 'sep' : el.matches('[data-zone-popout]') ? 'pop out' : 'close'));
    expect(parts).toEqual(['icon', 'name', 'bar', 'sep', 'close']);
    expect(section().querySelector('[data-rail-body] [data-probe-bar]')).toBeNull();
    head.querySelector<HTMLButtonElement>('[data-head-close]')!.click();
    flushSync();
    expect(railStores.side.layout.sections[0]!.map((item) => item.widget)).toEqual(['core.files']);
    expect(railSlideout.shown('side')).toEqual([]);
  });

  test('the header\'s own menu turns it back off', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes', options: { show_header: true } }));
    openNotes();
    section().querySelector<HTMLButtonElement>('[data-corner]')!.click();
    flushSync();
    const tick = document.querySelector<HTMLElement>('.acm-menu [data-node="show-header"]')!;
    expect(tick.getAttribute('aria-checked')).toBe('true');
    tick.click();
    flushSync();
    expect(railStores.side.layout.sections[0]![0]!.options).toEqual({ show_header: false });
    expect(section().querySelector('[data-widget-head]')).toBeNull();
  });
});
