/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

const served = vi.hoisted(() => ({
  document: { status: 'ok', revision: 0, items: { widget: {}, plugin: {} } } as Record<string, unknown>,
  patches: [] as { path: string; body: Record<string, unknown> }[],
  refuse: false,
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (route: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'PATCH') {
        if (served.refuse) throw new real.ApiError('refused', 400);
        served.patches.push({ path: route, body: JSON.parse(init.body ?? '{}') });
        const values = (JSON.parse(init.body ?? '{}') as { values: Record<string, unknown> }).values;
        const widget = (served.document.items as { widget: Record<string, unknown> }).widget;
        const held = (widget['core.files'] as { values?: Record<string, unknown> } | undefined)?.values ?? {};
        widget['core.files'] = { values: { ...held, ...values }, revision: 1 };
        return {};
      }
      if (route !== '/item-settings') throw new real.ApiError('not in this test', 404);
      return structuredClone(served.document);
    },
  };
});

import { filesRootPrefs, publishRootPrefs } from './roots-prefs.svelte';
import { itemSettings } from '../item-settings/store.svelte';
import { auth } from '../../opscenter/api/auth.svelte';
import { HEADER_ID, mountFileDrawerHeader } from './file-drawer';
import { unmountPanel } from '../mount';

const REPO = path.resolve(process.cwd(), '..');

function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<div class="modal-overlay config-editor-picker-overlay"');
  const end = source.indexOf('<!-- Auth Screen -->', start);
  return source.slice(start, end);
}

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  flushSync();
}

beforeEach(async () => {
  auth.state = 'signed-in';
  served.document = { status: 'ok', revision: 0, items: { widget: {}, plugin: {} } };
  served.patches = [];
  served.refuse = false;
  await itemSettings.refresh(true);
});

afterEach(() => {
  unmountPanel(HEADER_ID);
  document.body.innerHTML = '';
  delete (globalThis as { ConfigEditorRoots?: unknown }).ConfigEditorRoots;
});

describe('the settings', () => {
  test('default to the global folder shown and on top', () => {
    expect(filesRootPrefs()).toEqual({ showGlobal: true, topFolder: 'global' });
  });

  test('follow the stored choice', async () => {
    served.document = {
      status: 'ok', revision: 1,
      items: { widget: { 'core.files': { values: { showGlobalFolder: false, topFolder: 'project' }, revision: 1 } }, plugin: {} },
    };
    await itemSettings.refresh(true);
    expect(filesRootPrefs()).toEqual({ showGlobal: false, topFolder: 'project' });
  });

  test('publishRootPrefs reaches the legacy roots module and reports its answer', () => {
    expect(publishRootPrefs({ showGlobal: false, topFolder: 'global' })).toBe(false);
    const setPrefs = vi.fn(() => true);
    (globalThis as { ConfigEditorRoots?: unknown }).ConfigEditorRoots = { setPrefs };
    expect(publishRootPrefs({ showGlobal: false, topFolder: 'project' })).toBe(true);
    expect(setPrefs).toHaveBeenCalledWith({ showGlobal: false, topFolder: 'project' });
  });
});

describe('the options menu quick option', () => {
  function mount(): HTMLElement {
    document.body.innerHTML = drawerMarkup();
    const onPrefs = vi.fn();
    mountFileDrawerHeader({
      onQuery: vi.fn(), onPrefs, onRefresh: vi.fn(), onCollapseAll: vi.fn(), onNewFile: vi.fn(), onClose: vi.fn(),
    });
    flushSync();
    const root = document.getElementById(HEADER_ID) as HTMLElement;
    (root.querySelector('[data-action="options"]') as HTMLButtonElement).click();
    flushSync();
    return root;
  }

  test('unchecking show global folder writes showGlobalFolder through the item-settings route', async () => {
    const root = mount();
    const box = root.querySelector('[data-pref="showGlobalFolder"]') as HTMLInputElement;
    expect(box.checked).toBe(true);
    box.click();
    await settle();
    expect(served.patches).toEqual([{ path: '/item-settings/widget/core.files', body: { values: { showGlobalFolder: false } } }]);
    expect(filesRootPrefs().showGlobal).toBe(false);
    expect((root.querySelector('[data-pref="projectOnTop"]') as HTMLInputElement).disabled).toBe(true);
  });

  test('project on top writes topFolder, and the legacy module is told', async () => {
    const setPrefs = vi.fn(() => false);
    (globalThis as { ConfigEditorRoots?: unknown }).ConfigEditorRoots = { setPrefs };
    const root = mount();
    (root.querySelector('[data-pref="projectOnTop"]') as HTMLInputElement).click();
    await settle();
    expect(served.patches[0]?.body).toEqual({ values: { topFolder: 'project' } });
    expect(setPrefs).toHaveBeenLastCalledWith({ showGlobal: true, topFolder: 'project' });
  });

  test('a refused write shows a line instead of staying silent', async () => {
    served.refuse = true;
    const root = mount();
    (root.querySelector('[data-pref="showGlobalFolder"]') as HTMLInputElement).click();
    await settle();
    expect(root.querySelector('.fdh-note')).not.toBeNull();
    expect(filesRootPrefs().showGlobal).toBe(true);
  });
});
