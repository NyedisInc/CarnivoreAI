/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DrawerMenu from './DrawerMenu.svelte';
import { RAIL_DESTINATIONS, RAIL_HELP_LINKS } from '../../opscenter/shell/rail-items';
import { navAnchors } from '../../opscenter/engine/navAnchors.svelte';
import { setLocale } from '../i18n/index.svelte';
import { viewport } from '../../opscenter/engine/viewport.svelte';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';

// Task Manager is on by default for a clean install since 2026-10-05 (docs/cplugs.md section 9 question 1, superseded);
// these tests pin its enablement explicitly instead of leaning on the default.
cplugEnablement.enabled = { huddle: true };

setLocale('en');

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;
const mounted: ReturnType<typeof mount>[] = [];

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete win.App;
  delete win.CloudeWeb;
  delete win.SessionSidebarPin;
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(DrawerMenu, { target }));
  flushSync();
  return target;
}

const row = (root: HTMLElement, id: string) =>
  root.querySelector<HTMLButtonElement>(`[data-rail-item="${id}"]`)!;

const FORMER_RAIL: Array<[string, string]> = [
  ['dashboards', 'dashboard'],
  ['sessions', 'projects'],
  ['automations', 'automations'],
  ['warez', 'warez'],
  ['widgets', 'widgets'],
  ['blueprints', 'blueprints'],
  ['providers', 'providers'],
  ['hosts', 'pack'],
  ['docs', 'documentation'],
  ['changelog', 'changelog'],
  ['settings', 'settings'],
];

test('the menu draws every row the home rail had, in order', () => {
  const root = render();
  const drawn = [...root.querySelectorAll<HTMLButtonElement>('[data-rail-item]')].map((b) => [
    b.dataset.railItem,
    b.querySelector('.oc-nav-label')?.textContent?.trim(),
  ]);
  expect(drawn).toEqual(FORMER_RAIL);
});

test('the help heading sits between the first group and documentation; no huddle row; changelog has its own icon', () => {
  const root = render();
  const nav = root.querySelector('nav')!;
  const head = nav.querySelector('h2.oc-sidebar-head')!;
  expect(head.textContent?.trim()).toBe('help');
  expect(nav.querySelector('[data-rail-item="huddle"]')).toBeNull();
  const settings = row(root, 'settings');
  const docs = row(root, 'docs');
  expect(head.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(docs.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(head.compareDocumentPosition(docs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const icon = (id: string) => row(root, id).querySelector('.oc-nav-icon')!.innerHTML;
  expect(icon('changelog')).not.toBe('');
  expect(icon('changelog')).not.toBe(icon('docs'));
});

test('the dashboards row goes to the default dashboard and the drawer is told to put itself away', () => {
  const showLaunchpad = vi.fn();
  const closeAfterSwitch = vi.fn();
  win.App = { showLaunchpad };
  win.SessionSidebarPin = { closeAfterSwitch };
  const home = row(render(), 'dashboards');
  expect(home.getAttribute('aria-current')).toBeNull();
  home.click();
  expect(showLaunchpad).toHaveBeenCalledTimes(1);
  expect(closeAfterSwitch).toHaveBeenCalledTimes(1);
});

test('widgets opens the widgets manager page, not the arrange popover (issue #1065)', () => {
  const openWidgetsScreen = vi.fn(() => true);
  win.CloudeWeb = { openWidgetsScreen };
  row(render(), 'widgets').click();
  expect(openWidgetsScreen).toHaveBeenCalledTimes(1);
});

test('documentation and changelog each open their own page (were inert rows)', () => {
  for (const [id, container] of [
    ['docs', 'docs-screen'],
    ['changelog', 'changelog-screen'],
  ] as const) {
    const host = document.createElement('div');
    host.id = container;
    document.body.append(host);
    const item = [...RAIL_DESTINATIONS, ...RAIL_HELP_LINKS].find((i) => i.id === id)!;
    expect(item.run, `${id} has an action`).toBeTypeOf('function');
    item.run!();
    expect(host.children.length, `${id} mounted its page`).toBeGreaterThan(0);
    host.remove();
  }
});

test('the pack row opens the pack page, closing the others first (Alex (Example-owner), 2026-10-13)', () => {
  const openHostsScreen = vi.fn(() => true);
  win.CloudeWeb = { openHostsScreen };
  row(render(), 'hosts').click();
  expect(openHostsScreen).toHaveBeenCalledTimes(1);
});

test('providers opens the provider ledger page in the menu-page frame', () => {
  const openLedgerScreen = vi.fn(() => true);
  win.CloudeWeb = { openLedgerScreen };
  row(render(), 'providers').click();
  expect(openLedgerScreen).toHaveBeenCalledTimes(1);
});

test('the Components row (phone) is the flight anchor while it is mounted', async () => {
  navAnchors.components = null;
  viewport.wide = false;
  try {
    const root = render();
    expect(navAnchors.components).toBe(row(root, 'components'));
    for (const c of mounted.splice(0)) await unmount(c);
    expect(navAnchors.components).toBeNull();
  } finally {
    viewport.wide = true;
  }
});

test('the arrange screen row is gone on a desktop and stays on a phone, where edit layout does not exist', () => {
  try {
    viewport.wide = true;
    expect(render().querySelector('[data-rail-item="components"]')).toBeNull();
    document.body.replaceChildren();
    viewport.wide = false;
    expect(render().querySelector('[data-rail-item="components"]')).not.toBeNull();
  } finally {
    viewport.wide = true;
  }
});
