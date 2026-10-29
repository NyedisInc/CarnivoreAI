/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api', () => ({
  auth: { state: 'signed-in' },
  initAuth: () => {},
  startEvents: () => {},
}));

import { TAB_WINDOW_DEFAULT, openTabPopout, tabFromSearch, tabGeometryKey, tabPath, tabWindowName } from './tab-popout';
import { POPOUT_TABS, popoutTab } from './popout-tabs';
import { BUILTIN_TABS } from './builtin';
import { createTabRegistry } from './registry';
import { sidebarTabs } from './tab-store.svelte';
import DynamicTabBody from './DynamicTabBody.svelte';
import TabPopout from '../../popout/TabPopout.svelte';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';

// Task Manager is on by default for a clean install since 2026-10-05 (docs/cplugs.md section 9 question 1, superseded);
// these tests pin its enablement explicitly instead of leaning on the default.
cplugEnablement.enabled = { huddle: true };
import type { DynamicTabDef } from './types';

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

test('the url names one tab id and refuses anything else', () => {
  expect(tabFromSearch('?tab=huddle')).toBe('huddle');
  expect(tabFromSearch('?tab=../x')).toBeNull();
  expect(tabFromSearch('?tab=Huddle')).toBeNull();
  expect(tabFromSearch('?widget=core.notes')).toBeNull();
  expect(tabPath('huddle')).toBe('/static/popout.html?tab=huddle');
});

test('opening a tab names its own window, at its last size or the sidebar default', () => {
  const open = vi.fn(() => ({ focus: () => {} }) as unknown as Window);
  const win = { open } as unknown as Window;
  openTabPopout('huddle', win);
  expect(open).toHaveBeenCalledWith('/static/popout.html?tab=huddle', tabWindowName('huddle'),
    `popup=yes,width=${TAB_WINDOW_DEFAULT.width},height=${TAB_WINDOW_DEFAULT.height}`);
  localStorage.setItem(tabGeometryKey('huddle'), JSON.stringify({ width: 600, height: 500, left: 10, top: 20 }));
  openTabPopout('huddle', win);
  expect(open).toHaveBeenLastCalledWith(expect.any(String), expect.any(String), 'popup=yes,width=600,height=500,left=10,top=20');
  expect(openTabPopout('Not A Tab', win)).toBeNull();
});

test('every tab that declares popout is on the pop-out ship list, and only those', () => {
  const declared = BUILTIN_TABS.filter((d) => d.popout).map((d) => d.id).sort();
  expect(POPOUT_TABS.map((d) => d.id).sort()).toEqual(declared);
  expect(declared).toContain('huddle');
  expect(popoutTab('agents')).toBeNull();
});

test('the registry refuses a pop-out on a body that cannot leave the page', () => {
  const registry = createTabRegistry();
  const base = { labelKey: 'x', icon: 'chat', persist: false, widgetArea: 'glance' } as const;
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  expect(registry.register({ ...base, id: 'a', order: 1, popout: true, body: { containers: ['x'] } } as DynamicTabDef)).toBe('popout');
  const body = POPOUT_TABS[0]!.body;
  if (!('component' in body)) throw new Error('the huddle body is a component body');
  const component = body.component;
  expect(registry.register({ ...base, id: 'b', order: 2, popout: true, body: { component } } as DynamicTabDef)).toBe('popout');
  expect(registry.register({ ...base, id: 'c', order: 3, popout: true, body: { component, titleKey: 'x' } } as DynamicTabDef)).toBeNull();
});

test('a pop-out tab draws the pop out key in its title row, and it opens the tab window', () => {
  const open = vi.spyOn(window, 'open').mockImplementation(() => null);
  sidebarTabs.select('huddle');
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(DynamicTabBody, { target: host });
  flushSync();
  const key = host.querySelector<HTMLElement>('[data-tab-popout="huddle"]');
  expect(key).not.toBeNull();
  expect(host.querySelector('[data-task-manager-send]')).not.toBeNull();
  key!.click();
  expect(open).toHaveBeenCalledWith('/static/popout.html?tab=huddle&list=aggregate', expect.stringMatching(/^carnivore-tab-huddle-\w+$/), expect.stringContaining('popup=yes'));
});

test('the pop-out page shows the tab alone, and a notice for a tab it does not list', () => {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TabPopout, { target: host, props: { tab: 'huddle' } });
  flushSync();
  expect(host.querySelector('[data-popout-tab="huddle"]')).not.toBeNull();
  expect(host.querySelector('[data-task-manager-body][data-popout="on"]')).not.toBeNull();
  expect(host.querySelector('[data-tab-popout]')).toBeNull();
  unmount(app);
  app = mount(TabPopout, { target: host, props: { tab: 'agents' } });
  flushSync();
  expect(host.querySelector('[data-tab-unavailable]')).not.toBeNull();
});

test('a multi tab opens each pop-out under its own window name, a plain one reuses its window', () => {
  const open = vi.fn(() => ({ focus: () => {} }) as unknown as Window);
  const win = { open } as unknown as Window;
  openTabPopout('huddle', win, { list: '18' }, true);
  openTabPopout('huddle', win, { list: '19' }, true);
  const names = open.mock.calls.map((call) => (call as unknown as string[])[1]);
  expect(names[0]).not.toBe(names[1]);
  expect(names.every((name) => (name ?? '').startsWith(`${tabWindowName('huddle')}-`))).toBe(true);
  openTabPopout('huddle', win);
  openTabPopout('huddle', win);
  expect((open.mock.calls[2] as unknown as string[])[1]).toBe(tabWindowName('huddle'));
  expect((open.mock.calls[3] as unknown as string[])[1]).toBe(tabWindowName('huddle'));
});
