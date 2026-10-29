/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const fake = vi.hoisted(() => ({ answers: [] as unknown[] }));

vi.mock('../../api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  authFetch: () => {
    const next = fake.answers.shift();
    return Promise.resolve(next ?? { status: 'unchanged', body: '', revision: 0, updated_at: null });
  },
}));
vi.mock('../../api/events.svelte', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  subscribe: () => () => {},
}));
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  primarySessionId: () => 'ses_1',
  sessions: { get data() { return [{ session: { id: 'ses_1' }, tmux_session: 'cloude_api' }]; } },
}));

import NotesDrawer from '../../../lib/notes-header/NotesDrawer.svelte';
import { openDrawer, resetRightDrawerForTest } from '../../../lib/right-drawer/dock.svelte';
import PlacementBody from '../../../lib/zone-shell/PlacementBody.svelte';
import NotesFrame from '../../shell/fixtures/NotesFrame.svelte';
import NotesCell from './Cell.svelte';
import { META } from '../../engine/meta';
import { reset } from '../../api/notes.svelte';
import { viewport } from '../../engine/viewport.svelte';
import { sizes } from '../../engine/observe.svelte';
import { CORE_MANIFESTS, coreWidgetId } from '../../widgets/core-manifests';

async function drawn(draw: (target: HTMLElement) => object): Promise<{ target: HTMLElement; app: object }> {
  fake.answers = [{ status: 'unchanged', body: 'note', revision: 1, updated_at: '2026-10-12T12:00:00+00:00' }];
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = draw(target);
  flushSync();
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  return { target, app };
}

function rowOrder(row: Element): string[] {
  return [...row.children].map((child) => {
    const el = child as HTMLElement;
    if (el.hasAttribute('data-notes-controls')) return 'controls';
    if (el.classList.contains('oc-head-group') && el.querySelector(':scope > [data-notes-controls]')) return 'controls';
    if (el.hasAttribute('data-notes-label')) return 'label';
    if (el.classList.contains('oc-notes-mode')) return 'toggle';
    if (el.classList.contains('oc-notes-disk-wrap')) return 'disk';
    return el.className.split(' ')[0] || el.tagName.toLowerCase();
  });
}

function controlsIn(root: Element): HTMLElement {
  return root.querySelector('[data-notes-controls]') as HTMLElement;
}

function ruleOf(path: string, selector: string): string {
  const text = readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8');
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(?:^|\\n)\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(text);
  return match ? match[1]! : '';
}

function grows(rule: string): boolean {
  return /flex:\s*1 1 auto/.test(rule);
}

beforeEach(() => {
  vi.useFakeTimers();
  fake.answers = [];
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  reset();
});

afterEach(() => {
  for (const key of Object.keys(sizes)) delete sizes[key];
  viewport.phone = false;
  viewport.wide = true;
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('"notes" on the left, the controls at the right end', () => {
  test('grid: the title, the spacer, then the controls, and the name is printed once', async () => {
    const { target, app } = await drawn((el) => mount(NotesFrame, { target: el }));
    const row = target.querySelector('.oc-frame-title') as HTMLElement;
    const order = rowOrder(row);
    const name = order.indexOf('oc-frame-name');
    const spacer = order.indexOf('oc-frame-spacer');
    const controls = order.indexOf('controls');
    expect(name).toBeGreaterThanOrEqual(0);
    expect(spacer).toBeGreaterThan(name);
    expect(controls).toBe(spacer + 1);
    expect(order.slice(controls + 1)).toEqual(['oc-head-sep', 'button']);
    expect(row.querySelector('[data-head-close]')).not.toBeNull();
    expect(grows(ruleOf('../../shell/WidgetHead.svelte', '.oc-frame-spacer'))).toBe(true);
    expect(row.querySelector('.oc-frame-name')?.textContent).toBe('notes');
    expect(target.querySelectorAll('[data-notes-controls]')).toHaveLength(1);
    expect(target.querySelector('[data-notes-label]')).toBeNull();
    expect(rowOrder(controlsIn(row))).toEqual(['toggle', 'disk']);
    unmount(app, { outro: false });
  });

  test('grid below 1024 (the phone stack): the growing heading, then the controls', async () => {
    viewport.phone = true;
    viewport.wide = false;
    const { target, app } = await drawn((el) => mount(NotesFrame, { target: el }));
    const row = target.querySelector('.oc-frame-title') as HTMLElement;
    const heading = row.querySelector('.oc-frame-name-wrap') as HTMLElement;
    expect(heading).not.toBeNull();
    expect([...heading.classList].filter((name) => !name.startsWith('svelte-')).sort()).toEqual(['oc-frame-name', 'oc-frame-name-wrap']);
    expect(grows(ruleOf('../../shell/WidgetHead.svelte', '.oc-frame-name-wrap'))).toBe(true);
    const order = rowOrder(row);
    const name = order.indexOf('oc-frame-name');
    expect(name).toBeGreaterThanOrEqual(0);
    expect(order.indexOf('controls')).toBe(name + 1);
    expect(order).not.toContain('oc-frame-spacer');
    expect(rowOrder(controlsIn(row))).toEqual(['toggle', 'disk']);
    unmount(app, { outro: false });
  });

  test('right drawer: the zone header row, notes on the left, the toggle and disk, open as widget, then the close x', async () => {
    openDrawer('notes');
    const { target, app } = await drawn((el) => mount(NotesDrawer, {
      target: el,
      props: { onClose: () => {}, onComponent: () => {}, canComponent: () => true },
    }));
    expect(target.querySelector('.nd-head'), 'no hand-drawn head row').toBeNull();
    const rows = target.querySelectorAll('[data-widget-head]');
    expect(rows).toHaveLength(1);
    const row = rows[0] as HTMLElement;
    const order = rowOrder(row);
    expect(order).toEqual(['oc-frame-cornerwrap', 'oc-frame-name', 'oc-frame-spacer', 'controls', 'oc-head-sep', 'oc-head-group', 'oc-head-sep', 'button']);
    expect(row.querySelector('[data-corner]'), 'the icon that opens the one menu').not.toBeNull();
    expect(row.querySelector('.oc-frame-nametext, .oc-frame-name')?.textContent?.trim()).toBe('notes');
    expect(rowOrder(controlsIn(row))).toEqual(['toggle', 'disk']);
    const groups = [...row.querySelectorAll(':scope > .oc-head-group')];
    expect(groups[0]?.querySelector('[data-notes-controls]')).not.toBeNull();
    expect(groups[1]?.querySelector('[data-notes-drawer="as-component"]')).not.toBeNull();
    expect(order[order.length - 1]).toBe('button');
    expect(row.lastElementChild?.hasAttribute('data-head-close')).toBe(true);
    unmount(app, { outro: false });
    resetRightDrawerForTest();
  });

  test('rail slide-out, header off: no title row, no name and no control at all; edit, preview and save are menu items', async () => {
    const manifest = CORE_MANIFESTS[coreWidgetId('notes')];
    if (!manifest) throw new Error('no core notes manifest');
    sizes[`session-rail:${manifest.id}`] = { width: 480, height: 400 };
    const { target, app } = await drawn((el) => mount(PlacementBody, { target: el, props: { host: 'rail', manifest, pinRowId: null } }));
    expect(target.querySelector('[data-rail-body]')).not.toBeNull();
    expect(target.querySelector('[data-notes-controls], [data-notes-toggle]')).toBeNull();
    expect(target.querySelector('[data-notes-label], [data-notes-mode], [data-notes-save], [data-notes-empty]')).toBeNull();
    unmount(app, { outro: false });
  });

  test('rail slide-out with its header ticked on: the controls go up into the header, after its spacer, unlabelled', async () => {
    const manifest = CORE_MANIFESTS[coreWidgetId('notes')];
    if (!manifest) throw new Error('no core notes manifest');
    sizes[`session-rail:${manifest.id}`] = { width: 480, height: 400 };
    const { target, app } = await drawn((el) => mount(PlacementBody, {
      target: el,
      props: { host: 'rail', manifest, pinRowId: null, placementKey: manifest.id, options: { show_header: true } },
    }));
    const row = target.querySelector('[data-widget-head]') as HTMLElement;
    expect(row).not.toBeNull();
    const order = rowOrder(row);
    const spacer = order.indexOf('oc-frame-spacer');
    expect(spacer).toBeGreaterThan(order.indexOf('oc-frame-name'));
    expect(order.indexOf('controls')).toBe(spacer + 1);
    expect(row.querySelector('.oc-frame-name')?.textContent).toBe('notes');
    expect(target.querySelectorAll('[data-notes-controls]')).toHaveLength(1);
    expect(target.querySelector('[data-rail-body] [data-notes-controls]')).toBeNull();
    expect(target.querySelector('[data-notes-label]')).toBeNull();
    unmount(app, { outro: false });
  });

  test('drawer card with its header ticked off: no bar anywhere (menu only), unlabelled', async () => {
    const manifest = CORE_MANIFESTS[coreWidgetId('notes')];
    if (!manifest) throw new Error('no core notes manifest');
    sizes[`drawer-zone:${manifest.id}`] = { width: 320, height: 400 };
    const { target, app } = await drawn((el) => mount(PlacementBody, {
      target: el,
      props: { host: 'drawer', manifest, options: { show_header: false } },
    }));
    expect(target.querySelector('[data-widget-head] [data-notes-controls]')).toBeNull();
    expect(target.querySelector('[data-notes-controls]')).toBeNull();
    expect(target.querySelector('[data-notes-label]')).toBeNull();
    unmount(app, { outro: false });
  });

  test('a host with no header slot (a dynamic tab, a specimen): the bar names nothing and ends with the controls', async () => {
    const { target, app } = await drawn((el) => mount(NotesCell, {
      target: el,
      props: { width: 400, height: 400, meta: META.notes, instance: 'notes' },
    }));
    const bar = controlsIn(target);
    expect(bar).not.toBeNull();
    expect(rowOrder(bar)).toEqual(['toggle', 'disk']);
    expect(target.querySelector('[data-notes-label]')).toBeNull();
    expect(ruleOf('../../../lib/editor-controls/EditorControls.svelte', '.oc-notes-controls')).toMatch(/justify-content:\s*flex-end/);
    unmount(app, { outro: false });
  });
});
