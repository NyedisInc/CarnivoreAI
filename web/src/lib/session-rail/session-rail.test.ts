/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fakeActive } from './test-support.svelte';

const listing = vi.hoisted(() => ({
  data: [
    { session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/work/app' } },
    { session_row_id: 8, project_id: 5, session: { id: 'ses_2', working_dir: '/work/docs' } },
  ] as unknown[],
}));

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: listing, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { railStores, railDrags, railDrag, placeInRail } from './rail-store.svelte';
import { railSlideout } from './slideout.svelte';
import { RAIL_BOTTOM_ID, RAIL_FIELD, RAIL_ID, RAIL_SPECS } from './rail-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { beginDrawerCarry } from '../../opscenter/layout-editor/drawer-carry';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { scopeForWidget, sessionScopeFor } from '../../opscenter/widgets/session-scope';
import { activeScopeFor } from '../../opscenter/widgets/active-scope';
import { widgetSizeNames } from '../../opscenter/widgets/info/widget-info';
import type { LayoutStore } from '../../opscenter/engine/layout.svelte';
import { batches, BOTTOM_FIELD, follow, keysIn, layOutRail, mountRails, ptr, unmountRails, written } from './rail-test-harness';

const source = (file: string): string => readFileSync(join(process.cwd(), 'src', file), 'utf8');

const layOut = (): void => layOutRail('side');
const layOutBottom = (): void => layOutRail('bottom');
const keys = (): string[] => keysIn('side');
const bottomKeys = (): string[] => keysIn('bottom');

/** The stored v2 value of a one-section rail. */
const one = (...widgets: string[]) => ({ v: 2, sections: [{ items: widgets.map((widget) => ({ widget })) }] });

beforeEach(() => {
  fakeActive.id = 'ses_1';
  mountRails();
});

afterEach(() => {
  unmountRails();
});

describe('the default and the lists', () => {
  test('absent draws files, notes and bookmarks on the side, the terminal widget and scheduled tasks on the bottom, and writes nothing', () => {
    expect(keys()).toEqual(['core.files', 'core.notes', 'core.bookmarks']);
    expect(bottomKeys()).toEqual(['core.shell', 'core.scheduled-tasks']);
    expect(written).toEqual([]);
  });

  test('another device reordering the rail repaints it live (the preferences.changed follow)', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }, { widget: 'core.changes' }] });
    expect(keys()).toEqual(['core.task-manager', 'core.changes']);
    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
    expect(bottomKeys()).toEqual(['core.notes']);
    expect(written).toEqual([]);
  });
});

describe('an empty rail', () => {
  test('takes no space outside edit layout and is a labelled drop zone inside it', () => {
    follow(RAIL_FIELD, { v: 1, items: [] });
    follow(BOTTOM_FIELD, { v: 1, items: [] });
    expect(document.getElementById(RAIL_ID)).toBeNull();
    expect(document.getElementById(RAIL_BOTTOM_ID)).toBeNull();

    layoutEditor.active = true;
    flushSync();
    for (const id of [RAIL_ID, RAIL_BOTTOM_ID]) {
      const rail = document.getElementById(id)!;
      expect(rail).not.toBeNull();
      expect(rail.dataset['editing']).toBe('true');
      expect(rail.querySelector('[data-rail-empty]')?.textContent).toBe('drop widgets here');
    }

    layoutEditor.active = false;
    flushSync();
    expect(document.getElementById(RAIL_BOTTOM_ID)).toBeNull();
  });
});

describe('the bottom rail', () => {
  test('is the same component laid out horizontally, with no cap and a horizontal scroll', () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ widget: i % 2 ? 'core.changes' : 'core.files', target: `row:${i}` }));
    follow(BOTTOM_FIELD, { v: 1, items: many });
    const rail = document.getElementById(RAIL_BOTTOM_ID)!;
    expect(rail.dataset['railEdge']).toBe('bottom');
    expect(rail.classList.contains('rail--bottom')).toBe(true);
    expect(RAIL_SPECS.bottom.axis).toBe('x');
    expect(bottomKeys()).toHaveLength(30);
    const css = source('lib/session-rail/SessionRail.svelte') + source('lib/zone-shell/ZoneKeys.svelte');
    expect(css).toMatch(/\[data-axis='x'\] \.rail__keys \{[^}]*overflow-x: auto;/);
    expect(source('lib/session-rail/rail-layer.css')).toMatch(/\.rail--bottom \.rail__layer \{[^}]*flex-direction: row;/);
    expect(css).not.toMatch(/flex-wrap:\s*wrap/);
  });

  test('its slide-out comes up against the top edge of the rail and pushes the grid (rail-push.test.ts)', () => {
    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
    document.querySelector<HTMLButtonElement>(`#${RAIL_BOTTOM_ID} [data-zone-item="core.notes"]`)!.click();
    flushSync();
    const out = document.querySelector<HTMLElement>('[data-rail-slideout="core.notes"]')!;
    expect(out.dataset['railEdge']).toBe('bottom');
    expect(out.classList.contains('rail-out--bottom')).toBe(true);
    expect(out.closest(`#${RAIL_BOTTOM_ID}`)).not.toBeNull();
    const css = source('lib/session-rail/RailSlideout.svelte');
    expect(css).toMatch(/\.rail-out \{[^}]*position: absolute;/);
    expect(css).toMatch(/\.rail-out--bottom \{[^}]*bottom: 100%;/);
    expect(out.querySelector('.rail-out__bar')).toBeNull();
    expect(out.querySelector('[data-rail-close]')).toBeNull();
    expect(out.getAttribute('aria-label')).toBeTruthy();
    expect(out.querySelector('[data-rail-out-section]')?.getAttribute('aria-label')).toBeTruthy();
    const key = document.querySelector<HTMLButtonElement>(`#${RAIL_BOTTOM_ID} [data-zone-item="core.notes"]`)!;
    key.click();
    flushSync();
    expect(railSlideout.key).toBeNull();
    key.click();
    flushSync();
    expect(railSlideout.key).toBe('core.notes');
    document.querySelector('[data-rail-slideout]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(railSlideout.key).toBeNull();
    expect(source('lib/session-rail/SessionRail.svelte')).toMatch(/\.rail--bottom \{[^}]*height: var\(--rail-track, var\(--rail-h\)\);/);
    expect(document.getElementById(RAIL_BOTTOM_ID)!.style.getPropertyValue('--rail-h')).toBe('36px');
  });
});

describe('the slide-out', () => {
  test('a key slides its widget out over the terminal; the key again or Escape slide it back', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }, { widget: 'core.notes' }, { widget: 'core.task-manager' }] });
    const key = (id: string) => document.querySelector<HTMLButtonElement>(`[data-zone-item="${id}"]`)!;
    key('core.changes').click();
    flushSync();
    expect(document.querySelector('[data-rail-slideout]')?.getAttribute('data-rail-slideout')).toBe('core.changes');
    expect(key('core.changes').getAttribute('aria-expanded')).toBe('true');

    key('core.notes').click();
    flushSync();
    expect(document.querySelector('[data-rail-slideout="core.notes"]')).not.toBeNull();
    expect(railSlideout.key).toBe('core.notes');

    key('core.notes').click();
    flushSync();
    expect(railSlideout.key).toBeNull();

    key('core.task-manager').click();
    flushSync();
    expect(document.querySelector('[data-rail-slideout] .rail-out__bar')).toBeNull();
    document.querySelector('[data-rail-slideout]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(railSlideout.key).toBeNull();

    key('core.files').click();
    flushSync();
    document.querySelector('[data-rail-slideout]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(railSlideout.key).toBeNull();
  });
});

describe('the session-based flag', () => {
  test('a session-based widget follows the ACTIVE session and switches when it changes; others ignore sessions', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.notes' }, { widget: 'core.ledger' }] });
    document.querySelector<HTMLButtonElement>('[data-zone-item="core.notes"]')!.click();
    flushSync();
    const probe = (): HTMLElement => document.querySelector<HTMLElement>('[data-rail-body] [data-probe]')!;
    expect(probe().dataset['scope']).toBe('ses_1:4');
    expect(probe().dataset['page']).toBe('terminal');

    fakeActive.id = 'ses_2';
    flushSync();
    expect(probe().dataset['scope']).toBe('ses_2:5');

    document.querySelector<HTMLButtonElement>('[data-zone-item="core.ledger"]')!.click();
    flushSync();
    expect(probe().dataset['scope']).toBe('none');
  });

  test('every placement gets the same rule: the flag decides, the active session answers', () => {
    for (const id of ['core.changes', 'core.task-manager', 'core.notes', 'core.files']) {
      expect(CORE_MANIFESTS[id]!.scope).toBe('session');
    }
    expect(activeScopeFor(CORE_MANIFESTS['core.notes'])?.sessionId).toBe('ses_1');
    fakeActive.id = 'ses_2';
    expect(activeScopeFor(CORE_MANIFESTS['core.files'])).toEqual({ sessionId: 'ses_2', rowId: 8, workingDir: '/work/docs', projectId: 5 });
    expect(activeScopeFor(CORE_MANIFESTS['core.ledger'])).toBeNull();
    expect(activeScopeFor(undefined)).toBeNull();
  });

  test('the dashboard grid host and the drawer area hand the cell that same scope', () => {
    for (const file of ['opscenter/CellHost.svelte', 'lib/zone-shell/PlacementBody.svelte']) {
      const text = source(file);
      expect(text, file).toContain('activeScopeFor(');
      expect(text, file).toMatch(/scope=\{(scoped|scope)\}/);
    }
  });

  test('the scope is read off the listing on the levels it lives on', () => {
    const scope = sessionScopeFor(listing.data as never, 'ses_1');
    expect(scope).toEqual({ sessionId: 'ses_1', rowId: 7, workingDir: '/work/app', projectId: 4 });
    expect(sessionScopeFor(null, 'ses_9')).toEqual({ sessionId: 'ses_9', rowId: null, workingDir: '', projectId: null });
    expect(sessionScopeFor(null, '')).toBeNull();
    expect(scopeForWidget(CORE_MANIFESTS['core.ledger'], scope)).toBeNull();
  });
});

describe('edit layout owns the rails', () => {
  test('a key carried down the rail moves there; a key carried off both rails is taken out', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }, { widget: 'core.notes' }, { widget: 'core.task-manager' }] });
    layoutEditor.active = true;
    flushSync();
    layOut();
    expect(railDrag.indexAt(1018, 60, 'core.changes')).toBe(1);
    const first = document.querySelector<HTMLElement>('[data-zone-item="core.changes"]')!;
    first.dispatchEvent(ptr('pointerdown', 1018, 20));
    first.dispatchEvent(ptr('pointermove', 1018, 60));
    first.dispatchEvent(ptr('pointermove', 1018, 90));
    flushSync();
    expect(document.querySelector(`#${RAIL_ID} [data-zone-mark]`)).not.toBeNull();
    first.dispatchEvent(ptr('pointerup', 1018, 90));
    flushSync();
    expect(keys()).toEqual(['core.files', 'core.notes', 'core.changes', 'core.task-manager']);

    layOut();
    const huddle = document.querySelector<HTMLElement>('[data-zone-item="core.task-manager"]')!;
    huddle.dispatchEvent(ptr('pointerdown', 1018, 120));
    huddle.dispatchEvent(ptr('pointermove', 600, 120));
    huddle.dispatchEvent(ptr('pointerup', 600, 120));
    flushSync();
    expect(keys()).toEqual(['core.files', 'core.notes', 'core.changes']);
    expect(written.at(-1)).toEqual({ field: RAIL_FIELD, value: one('core.files', 'core.notes', 'core.changes') });
  });

  test('a key dragged from the side rail onto the bottom rail moves across, and back again', () => {
    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }] });
    layoutEditor.active = true;
    flushSync();
    layOut();
    layOutBottom();
    expect(railDrags.bottom.indexAt(100, 718)).toBe(1);

    const dragged = document.querySelector<HTMLElement>('[data-zone-item="core.files"]')!;
    dragged.dispatchEvent(ptr('pointerdown', 1018, 20));
    dragged.dispatchEvent(ptr('pointermove', 400, 718));
    flushSync();
    expect(railDrags.bottom.state.index).toBe(1);
    dragged.dispatchEvent(ptr('pointerup', 400, 718));
    flushSync();
    expect(keys()).toEqual(['core.notes', 'core.bookmarks']);
    expect(bottomKeys()).toEqual(['core.task-manager', 'core.files']);
    expect(written.map((w) => w.field).sort()).toEqual([RAIL_FIELD, BOTTOM_FIELD].sort());
    expect(batches).toHaveLength(1);
    expect(batches[0]!.slice().sort()).toEqual([RAIL_FIELD, BOTTOM_FIELD].sort());

    layOut();
    layOutBottom();
    const notes = document.querySelector<HTMLElement>(`#${RAIL_BOTTOM_ID} [data-zone-item="core.task-manager"]`)!;
    notes.dispatchEvent(ptr('pointerdown', 20, 718));
    notes.dispatchEvent(ptr('pointermove', 1018, 5));
    notes.dispatchEvent(ptr('pointerup', 1018, 5));
    flushSync();
    expect(keys()).toEqual(['core.task-manager', 'core.notes', 'core.bookmarks']);
    expect(bottomKeys()).toEqual(['core.files']);
  });

  test('without a pointer: arrows along the strip move the focused key and del takes it out', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }, { widget: 'core.notes' }, { widget: 'core.task-manager' }] });
    layoutEditor.active = true;
    flushSync();
    const key = (id: string) => document.querySelector<HTMLElement>(`[data-zone-item="${id}"]`)!;
    key('core.task-manager').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    flushSync();
    expect(keys()).toEqual(['core.changes', 'core.files', 'core.task-manager', 'core.notes']);
    key('core.files').dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }));
    flushSync();
    expect(keys()).toEqual(['core.changes', 'core.task-manager', 'core.notes']);

    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.files' }, { widget: 'core.ledger' }] });
    document.querySelector<HTMLElement>(`#${RAIL_BOTTOM_ID} [data-zone-item="core.ledger"]`)!
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    flushSync();
    expect(bottomKeys()).toEqual(['core.ledger', 'core.files']);
  });

  test('a widget carried in from the layout editor drawer lands at the rail insertion point, on whichever rail it is over', () => {
    layoutEditor.active = true;
    flushSync();
    layOut();
    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
    layOutBottom();
    const card = document.createElement('div');
    document.body.appendChild(card);
    const store = { drag: { target: null }, clearDrag: () => {} } as unknown as LayoutStore;
    const landed: unknown[] = [];
    const none = { refusal: '', moves: null };
    beginDrawerCarry(card, ptr('pointerdown', 300, 300), { surface: null, zone: none, glance: none, rail: none }, store, 'terminal', null, {
      onMove: () => {},
      onDrop: (target) => { landed.push(target); },
      onRefuse: () => {},
      onEnd: () => {},
    });
    card.dispatchEvent(ptr('pointermove', 1018, 30));
    expect(railDrag.state.index).toBe(1);
    card.dispatchEvent(ptr('pointermove', 100, 718));
    expect(railDrag.state.index).toBeNull();
    expect(railDrags.bottom.state.index).toBe(1);
    card.dispatchEvent(ptr('pointerup', 100, 718));
    expect(landed).toEqual([{ area: 'rail', edge: 'bottom', spot: { section: 0, index: 1, split: null }, moves: null }]);
    card.remove();
  });
});

describe('the rails hold more than the drawer area and one widget in one rail', () => {
  test('placing a widget in one rail takes it out of the other', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }] });
    expect(placeInRail('bottom', 'core.files', { section: 0, index: 0, split: null })).toBe(true);
    flushSync();
    expect(keys()).toEqual(['core.changes']);
    expect(bottomKeys()).toEqual(['core.files', 'core.shell', 'core.scheduled-tasks']);
    expect(railStores.bottom.items.map((i) => i.widget)).toEqual(['core.files', 'core.shell', 'core.scheduled-tasks']);
  });
});

describe('the new widgets', () => {
  test('changes and huddle declare the list sizes, one copy per page, and the session flag', () => {
    for (const id of ['core.changes', 'core.task-manager']) {
      const manifest = CORE_MANIFESTS[id]!;
      expect(widgetSizeNames(manifest)).toEqual(['tall', 'medium', 'large', 'full']);
      expect(manifest.fits.max_per_surface).toBe(1);
      expect(manifest.scope).toBe('session');
    }
  });
});
