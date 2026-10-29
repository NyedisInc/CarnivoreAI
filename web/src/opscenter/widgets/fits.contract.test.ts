/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import { CELL_IDS, META } from '../engine/meta';
import { createLayoutStore } from '../engine/layout.svelte';
import { resetLayout } from '../engine/model';
import type { InstanceKind, LayoutPage, SlotId } from '../engine/types';
import { offered, type DrawerInputs } from '../layout-editor/drawer-model';
import { layoutEditor } from '../layout-editor/editor.svelte';
import CellMenu from '../engine/CellMenu.svelte';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import { CORE_MANIFESTS, coreWidgetId } from './core-manifests';
import { FIT_DECLARATIONS } from './fit-declarations';
import { checkFit, SIZE_UNIT_PX } from './fits';
import FrameFitBody from './chrome/FrameFitBody.svelte';
import { isViewCell } from './views';
import { validateManifest } from './validate';
import type { WidgetManifest } from './types';

installPopoverPolyfill();

const INSTANCE_KINDS: readonly InstanceKind[] = ['terminal', 'browser', 'analytics'];

let app: object | null = null;

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  layoutEditor.active = false;
  layoutEditor.page = null;
  document.body.innerHTML = '';
});

function inputs(page: LayoutPage, manifests?: Readonly<Record<string, WidgetManifest>>): DrawerInputs {
  const layout = resetLayout(META, page);
  return {
    page,
    onSurface: layout.rows.flatMap((row) => row.slots.map((slot) => slot.id as SlotId)),
    disabled: () => false,
    query: '',
    category: null,
    t: (key) => key,
    ...(manifests ? { manifests } : {}),
  };
}

describe('every widget declares the contract', () => {
  test('each cell and instance kind has a declaration, and its manifest validates with it', () => {
    for (const key of [...CELL_IDS, ...INSTANCE_KINDS]) {
      expect(FIT_DECLARATIONS[key], key).toBeDefined();
      const manifest = CORE_MANIFESTS[coreWidgetId(key)]!;
      expect(validateManifest(JSON.parse(JSON.stringify(manifest))).ok, key).toBe(true);
      expect('zones' in manifest.fits, key).toBe(false);
    }
  });

  test('a manifest without a declaration is refused', () => {
    const { fits: _dropped, ...bare } = JSON.parse(JSON.stringify(CORE_MANIFESTS['core.notes']));
    const check = validateManifest(bare);
    expect(check.ok).toBe(false);
    expect(check.ok ? null : check.refusal).toBe('fits');
  });
});

describe('every widget is offered everywhere', () => {
  test('a home widget is offered on the terminal page, and every singleton on home', () => {
    expect(offered(inputs('terminal')).map((item) => item.cell)).toContain('projects');
    const singletons = Object.values(CORE_MANIFESTS).filter((m) => m.instancing === 'singleton' && !isViewCell(m)).length;
    expect(offered(inputs('home')).length).toBe(singletons);
  });
});

describe('a misfit renders the not-available plate', () => {
  test('the check names the reason and the smallest size, and no place is a reason', () => {
    const fits = CORE_MANIFESTS['core.notes']!.fits;
    expect(checkFit(fits, { width: 800, height: 400 }).ok).toBe(true);
    const small = checkFit(fits, { width: 800, height: SIZE_UNIT_PX.h * 0.6 });
    expect(small).toMatchObject({ ok: false, reason: 'too-small', suggest: { h: fits.min.h } });
    expect(checkFit(fits, null)).toEqual({ ok: true });
  });

  test('a widget on the terminal page draws its own body (it once drew a zone refusal there)', () => {
    const store = createLayoutStore('terminal');
    const body = createRawSnippet(() => ({ render: () => '<p data-real-body>body</p>' }));
    const host = document.createElement('div');
    document.body.append(host);
    app = mount(FrameFitBody, { target: host, props: { meta: META['stat-running'], store, frame: null, titleRowPx: 0, body } });
    flushSync();
    expect(host.querySelector('[data-real-body]')).not.toBeNull();
    expect(host.querySelector('[data-widget-refusal]')).toBeNull();
  });

  test('a widget where it fits draws its own body', () => {
    const store = createLayoutStore('home');
    const body = createRawSnippet(() => ({ render: () => '<p data-real-body>body</p>' }));
    const host = document.createElement('div');
    document.body.append(host);
    app = mount(FrameFitBody, { target: host, props: { meta: META['stat-running'], store, frame: null, titleRowPx: 0, body } });
    flushSync();
    expect(host.querySelector('[data-real-body]')).not.toBeNull();
    expect(host.querySelector('[data-widget-refusal]')).toBeNull();
  });
});

describe('the gear menu in edit layout', () => {
  function openMenu(id: SlotId): HTMLElement {
    layoutEditor.active = true;
    layoutEditor.page = 'home';
    const anchor = document.createElement('button');
    document.body.append(anchor);
    app = mount(CellMenu, { target: document.body, props: { id, anchor, onClose: () => {}, store: createLayoutStore('home') } });
    flushSync();
    return document.querySelector<HTMLElement>('[role="menu"]')!;
  }

  test('settings... is offered for a configurable widget in edit layout, with close and no hide item', () => {
    const menu = openMenu('activity-log');
    expect(menu.querySelector('[data-node="settings"]')).not.toBeNull();
    expect(menu.querySelector('[data-node="report-a-problem"]')).toBeNull();
    expect(menu.querySelector('[data-node="close-widget"]')).not.toBeNull();
  });

  test('settings... is not offered for a widget with nothing to configure', () => {
    const menu = openMenu('notes');
    expect(menu.querySelector('[data-node="settings"]')).toBeNull();
    expect(menu.querySelector('[data-node="close-widget"]')).not.toBeNull();
  });
});
