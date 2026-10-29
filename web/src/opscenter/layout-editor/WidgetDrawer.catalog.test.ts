/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../api/sessions.svelte', () => ({ sessions: { data: [] } }));
vi.mock('../../lib/browser/api.svelte', () => ({ browsers: { data: [] } }));
vi.mock('../../lib/item-settings/store.svelte', () => ({ isWidgetDisabled: () => false }));
vi.mock('../../lib/help/feature-media', () => ({
  fetchFeatureMediaBlob: () => Promise.reject(new Error('no server in this test')),
}));

import WidgetDrawer from './WidgetDrawer.svelte';
import { homeLayout, terminalLayout, type LayoutStore } from '../engine/layout.svelte';
import { editorSeams, enterLayoutEditor, finishLayoutEditor } from './editor.svelte';
import { isViewCell } from '../widgets/views';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import type { LayoutPage } from '../engine/types';

installPopoverPolyfill();

const real = { ...editorSeams };
let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  finishLayoutEditor();
  Object.assign(editorSeams, real);
  document.body.replaceChildren();
});

function catalogOn(page: LayoutPage, store: LayoutStore, popout = false): string[] {
  store.resetAll();
  editorSeams.page = () => page;
  editorSeams.store = (p) => (p === page ? store : null);
  editorSeams.wide = () => true;
  enterLayoutEditor();
  const target = document.createElement('div');
  if (popout) target.id = 'popout-screen';
  document.body.append(target);
  app = mount(WidgetDrawer, { target, props: { store, page } });
  flushSync();
  const widgets = [...document.querySelectorAll<HTMLElement>('.le-list .le-card[data-widget]')].map((one) => one.dataset['widget']!);
  const windows = [...document.querySelectorAll<HTMLElement>('.le-card[data-picker-entry]')].map((one) => `window:${one.dataset['pickerEntry']}`);
  const out = [...new Set([...widgets, ...windows])].sort();
  unmount(app);
  app = null;
  finishLayoutEditor();
  document.body.replaceChildren();
  return out;
}

describe('one catalog on every surface', () => {
  test('home, a dashboard pop-out and the terminal page offer the same entries, and every widget is in them', () => {
    const home = catalogOn('home', homeLayout);
    const dashboard = catalogOn('home', homeLayout, true);
    const terminal = catalogOn('terminal', terminalLayout);
    expect(dashboard).toEqual(home);
    expect(terminal).toEqual(home);
    for (const manifest of Object.values(CORE_MANIFESTS).filter((m) => !isViewCell(m))) {
      const offered = manifest.type === 'pane' && manifest.instancing === 'per-target'
        ? home.includes(`window:${manifest.id === 'core.browser' ? 'browser' : 'terminal'}`)
        : home.includes(manifest.id);
      expect(offered, manifest.id).toBe(true);
    }
    expect(home).toEqual(expect.arrayContaining(['window:session', 'window:terminal', 'window:browser']));
  });
});
