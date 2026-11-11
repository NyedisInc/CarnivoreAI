/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DrawerMenu from './DrawerMenu.svelte';
import { setLocale } from '../i18n/index.svelte';
import FlyoutBodyFixture from '../sidebar-widgets/fixtures/FlyoutBodyFixture.svelte';
import { registerTab, tabRegistry } from '../dynamic-tabs/registry';
import { agentsTab, menuTab, questionsTab } from './core-tabs';
import { registerCoreSidebarWidgets } from '../sidebar-widgets/core-widgets';
import { registerSwarmFlyout } from '../../cplugs/huddle/swarm-flyout';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };
for (const def of [menuTab, agentsTab, questionsTab]) if (!tabRegistry.get(def.id)) registerTab(def);
if (!tabRegistry.get('huddle')) registerTab({ id: 'huddle', labelKey: 'cplug.huddle.tab', icon: 'swarm', order: 35, persist: false, widgetArea: 'glance', body: { component: FlyoutBodyFixture } });
registerCoreSidebarWidgets();
registerSwarmFlyout();
setLocale('en');

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;
const mounted: ReturnType<typeof mount>[] = [];
const openPluginsScreen = vi.fn();
const openSettingsScreen = vi.fn();
const openWrappersScreen = vi.fn();
const openHostsScreen = vi.fn();
const showLaunchpad = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(1_000_000);
  win.CloudeWeb = { openPluginsScreen, openSettingsScreen, openWrappersScreen, openHostsScreen };
  win.App = { showLaunchpad };
});

afterEach(async () => {
  vi.useRealTimers();
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  for (const f of [openPluginsScreen, openSettingsScreen, openWrappersScreen, openHostsScreen, showLaunchpad]) f.mockClear();
  delete win.App;
  delete win.CloudeWeb;
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(DrawerMenu, { target }));
  flushSync();
  return target;
}

function lines(root: HTMLElement): string[] {
  return [...root.querySelectorAll<HTMLElement>('ul.oc-nav > li')].flatMap((li) => {
    if (li.classList.contains('oc-nav-sep')) return ['|'];
    if (li.classList.contains('oc-nav-head')) return ['help'];
    if (li.classList.contains('oc-nav-fill')) return ['~'];
    if (li.classList.contains('oc-nav-sub') || li.classList.contains('oc-nav-components')) return [];
    const id = li.querySelector<HTMLElement>('[data-rail-item]')?.dataset.railItem;
    return id ? [id] : [];
  });
}

test('dividers follow swarm and pack, the help heading opens the help rows, settings is last after the fill', () => {
  const seq = lines(render());
  const swarm = seq.indexOf('core.swarm');
  expect(swarm).toBeGreaterThan(-1);
  expect(seq[swarm + 1], 'a divider after swarm').toBe('|');
  expect(seq.slice(seq.indexOf('hosts')), 'pack, a divider, the help heading, documentation, changelog, the fill, settings').toEqual(['hosts', '|', 'help', 'docs', 'changelog', '~', 'settings']);
  expect(seq.filter((l) => l === '|'), 'two dividers').toHaveLength(2);
});
