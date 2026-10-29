/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async () => ({ v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [], machines: [] }),
}));

import * as Search from '../drawer/search';
import { init as initStats, PREFERENCE_FIELD, statsShown } from '../drawer/stats-visibility.svelte';
import { setLocale } from '../i18n/index.svelte';
import { approvals } from '../approvals/approvals.svelte';
import { tabFlyoutId } from './tab-flyouts';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { closeDrawerAfterSwitch } from '../drawer-tabs/menu-hotkeys';
import { DRAWER_LIST_ID, DRAWER_SEARCH_ID, DRAWER_STATS_ID } from '../drawer-tabs/drawer-tabs';
import { SidebarWidgetRegistry } from './registry';
import { registerCoreSidebarWidgets } from './core-widgets';
import { registerSwarmFlyout } from '../../cplugs/huddle/swarm-flyout';
import { activeFlyout, flyoutShowsTab, openFlyout, railHostsTab } from './flyout.svelte';
import { initMenuPageEscape } from '../menu-page/menu-page-escape';
import { railEntries, widgetPresent } from './rail-model';
import { redirectTabToFlyout } from './rail-layout.svelte';
import { FLYOUT_CONTAINER_ID, RAIL_BODY_CLASS, RAIL_CONTAINER_ID, REGION_ID } from './rail-dom';
import { MENU_FLYOUT, QUESTIONS_FLYOUT, SESSION_LIST_WIDGET, SWARM_FLYOUT } from './widget-ids';
import FlyoutBodyFixture from './fixtures/FlyoutBodyFixture.svelte';
import { tabFlags } from './fixtures/tab-flags.svelte';
import { CLOSABLE_TAB, FLOW_TAB, closedTabs, HUDDLE, REPO, askOne, flyout, press, rail, railBtn, railOn, setupRail, unpinRail, settle, teardownRail } from './fixtures/rail-harness';

setLocale('en');

let store: Record<string, unknown>;

beforeEach(async () => {
  store = await setupRail();
});

afterEach(teardownRail);

test('T01: the pinned rail is the menu as icons: agents first, swarm second, questions (once it has data), the destinations, settings last', async () => {
  await railOn();
  const keys = (): (string | undefined)[] => [...rail().querySelectorAll<HTMLElement>('[data-rail-key]')].map((el) => el.dataset.railKey);
  expect(keys().slice(0, 2), 'no questions: the questions icon is not on the rail').toEqual([SESSION_LIST_WIDGET, SWARM_FLYOUT]);
  expect(keys().at(-1)).toBe('settings');
  expect(keys()).not.toContain(MENU_FLYOUT);
  await askOne();
  expect(document.body.classList.contains(RAIL_BODY_CLASS)).toBe(true);
  expect(keys().slice(0, 3)).toEqual([SESSION_LIST_WIDGET, SWARM_FLYOUT, QUESTIONS_FLYOUT]);
  expect(keys().at(-1)).toBe('settings');
  expect(activeFlyout()).toBeNull();
  expect(railBtn(SESSION_LIST_WIDGET).getAttribute('aria-pressed')).toBe('true');
  expect(flyout().classList.contains('sbr-flyout--open')).toBe(false);
  expect(flyout().inert || flyout().hasAttribute('inert')).toBe(true);
});

test('T02: the menu slides over the whole list region; the list and search stay mounted underneath', async () => {
  await railOn();
  Search.setQuery('alpha');
  await press(MENU_FLYOUT);
  expect(activeFlyout()).toBe(MENU_FLYOUT);
  const region = document.getElementById(REGION_ID)!;
  expect(region.contains(document.getElementById(FLYOUT_CONTAINER_ID))).toBe(true);
  expect(region.contains(document.getElementById(DRAWER_LIST_ID))).toBe(true);
  expect(region.contains(document.getElementById(DRAWER_SEARCH_ID))).toBe(true);
  expect(document.getElementById(DRAWER_LIST_ID)!.hidden).toBe(false);
  expect(document.querySelector(`#${DRAWER_SEARCH_ID} input`)).not.toBeNull();
  expect(Search.getQuery()).toBe('alpha');
  expect(flyout().classList.contains('sbr-flyout--open')).toBe(true);
  expect(flyout().dataset.flyout).toBe(MENU_FLYOUT);
  expect(flyout().querySelector('nav.oc-sidebar'), 'the menu is the existing DrawerMenu').not.toBeNull();
  expect(flyout().querySelector('.sbr-flyout__name')!.textContent).toBe('menu');
});

test('T03: picking a destination from the menu closes it in the same interaction', async () => {
  const closeAfterSwitch = vi.fn();
  vi.stubGlobal('SessionSidebarPin', { closeAfterSwitch });
  await railOn();
  await press(MENU_FLYOUT);
  flyout().querySelector<HTMLButtonElement>('li:not([data-menu-lead]) [data-rail-item]')!.click();
  await settle();
  expect(closeAfterSwitch, 'the row ran its destination').toHaveBeenCalled();
  expect(activeFlyout()).toBeNull();
});

test('T04: a press outside the menu closes it and the press still reaches its target', async () => {
  await railOn();
  await press(MENU_FLYOUT);
  const target = document.getElementById('main-target')!;
  const clicked = vi.fn();
  target.addEventListener('click', clicked);
  const down = new PointerEvent('pointerdown', { bubbles: true, cancelable: true });
  target.dispatchEvent(down);
  target.click();
  await settle();
  expect(down.defaultPrevented).toBe(false);
  expect(clicked).toHaveBeenCalledTimes(1);
  expect(activeFlyout()).toBeNull();
});

test('T05: questions stays open while you press and work in the main pane', async () => {
  await railOn();
  await askOne();
  await press(QUESTIONS_FLYOUT);
  const target = document.getElementById('main-target')!;
  target.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  target.click();
  await settle();
  expect(activeFlyout()).toBe(QUESTIONS_FLYOUT);
  expect(flyout().querySelector('.sbr-flyout__name')!.textContent).toBe('questions');
});

test('T06: with questions open, swarm swaps in directly: one slide-out, never agents in between', async () => {
  await railOn();
  await askOne();
  await press(QUESTIONS_FLYOUT);
  const seen: (string | null)[] = [];
  const observer = new MutationObserver(() => seen.push(flyout().classList.contains('sbr-flyout--open') ? flyout().dataset.flyout ?? null : null));
  observer.observe(flyout(), { attributes: true });
  await press(SWARM_FLYOUT);
  observer.disconnect();
  expect(activeFlyout()).toBe(SWARM_FLYOUT);
  expect(seen).not.toContain(null);
  expect(document.querySelectorAll(`#${FLYOUT_CONTAINER_ID} .sbr-flyout`).length).toBe(1);
  expect(flyout().querySelector('[data-fixture-dropdown]'), 'swarm is the huddle tab\'s own body').not.toBeNull();
  expect(flyoutShowsTab(HUDDLE)).toBe(true);
});

test('T07: Escape in an unpinned swarm slide-out returns to agents without changing the route', async () => {
  await railOn();
  await unpinRail();
  await press(SWARM_FLYOUT);
  const before = location.href;
  const close = flyout().querySelector<HTMLElement>('[data-flyout-close]')!;
  close.focus();
  close.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  await settle();
  expect(activeFlyout()).toBeNull();
  expect(location.href).toBe(before);
});

test('T08: Escape closes an inner dropdown before the slide-out', async () => {
  await railOn();
  await unpinRail();
  await press(SWARM_FLYOUT);
  const dropdown = flyout().querySelector<HTMLButtonElement>('[data-fixture-dropdown]')!;
  dropdown.click();
  await settle();
  expect(dropdown.getAttribute('aria-expanded')).toBe('true');
  dropdown.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  await settle();
  expect(dropdown.getAttribute('aria-expanded'), 'the dropdown closed first').toBe('false');
  expect(activeFlyout(), 'the slide-out stays').toBe(SWARM_FLYOUT);
  dropdown.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  await settle();
  expect(activeFlyout()).toBeNull();
});

test('Escape closes the slide-out while a hidden menu sits in the document (the header menu\'s closed panel)', async () => {
  const closedPanel = document.createElement('div');
  closedPanel.setAttribute('role', 'menu');
  closedPanel.hidden = true;
  const inHiddenParent = document.createElement('div');
  inHiddenParent.hidden = true;
  inHiddenParent.innerHTML = '<div role="menu"></div>';
  document.body.append(closedPanel, inHiddenParent);
  await railOn();
  await unpinRail();
  await press(SWARM_FLYOUT);
  const close = flyout().querySelector<HTMLElement>('[data-flyout-close]')!;
  const key = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
  close.dispatchEvent(key);
  await settle();
  expect(key.defaultPrevented).toBe(true);
  expect(activeFlyout()).toBeNull();
});

test('an open menu anywhere still takes the first Escape', async () => {
  const openMenu = document.createElement('div');
  openMenu.setAttribute('role', 'menu');
  document.body.append(openMenu);
  await railOn();
  await press(SWARM_FLYOUT);
  flyout().querySelector<HTMLElement>('[data-flyout-close]')!
    .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  await settle();
  expect(activeFlyout()).toBe(SWARM_FLYOUT);
});

test('a widget\'s own toolbar goes on a row below the title row, never over the icon, title and X', async () => {
  await railOn();
  await press(SWARM_FLYOUT);
  const title = flyout().querySelector<HTMLElement>('.sbr-flyout__title')!;
  const name = title.querySelector<HTMLElement>('.sbr-flyout__name');
  const close = title.querySelector<HTMLElement>('[data-flyout-close]');
  expect(name?.textContent?.trim()).toBe('swarm');
  expect(close).not.toBeNull();
  expect(title.querySelector('.sbr-flyout__icon')).not.toBeNull();
  for (const el of [title, name!, close!]) expect(el.closest('[hidden], [inert]'), el.className).toBeNull();
  const actions = flyout().querySelector<HTMLElement>('[data-fixture-actions]')!;
  expect(actions, 'the toolbar is drawn').not.toBeNull();
  expect(title.contains(actions), 'the toolbar is not in the title row').toBe(false);
  const row = actions.closest<HTMLElement>('.sbr-flyout__actions')!;
  expect(row.previousElementSibling, 'its row sits right under the title row').toBe(title);
});

test('T09: pressing the active icon again returns to agents, for each slide-out', async () => {
  await railOn();
  await askOne();
  for (const id of [MENU_FLYOUT, QUESTIONS_FLYOUT, SWARM_FLYOUT]) {
    await press(id);
    if (id !== MENU_FLYOUT) expect(railBtn(id).getAttribute('aria-pressed')).toBe('true');
    await press(id);
    expect(activeFlyout(), id).toBeNull();
    expect(railBtn(SESSION_LIST_WIDGET).getAttribute('aria-pressed')).toBe('true');
  }
});

test('T10: the agents icon returns to agents from any slide-out', async () => {
  await railOn();
  await askOne();
  for (const id of [MENU_FLYOUT, QUESTIONS_FLYOUT, SWARM_FLYOUT]) {
    await press(id);
    await press(SESSION_LIST_WIDGET);
    expect(activeFlyout(), id).toBeNull();
  }
});

test('T11: a question arriving shows the yellow count on the rail and never opens questions', async () => {
  await railOn();
  approvals.items = [{ id: 'q1', session_id: 's1', title: 'deploy?', created_at: new Date().toISOString() } as never];
  await settle();
  const badge = railBtn(QUESTIONS_FLYOUT).querySelector<HTMLElement>('[data-rail-badge]');
  expect(badge?.textContent).toBe('1');
  expect(railBtn(QUESTIONS_FLYOUT).getAttribute('aria-label')).toBe('questions, 1 waiting');
  expect(activeFlyout()).toBeNull();
});

test('T12: menu and agents stay fixed at the top; a registered widget cannot sort above them', () => {
  const registry = new SidebarWidgetRegistry();
  registerCoreSidebarWidgets(registry);
  registry.register({ id: 'x.first', titleKey: 'k', icon: 'bot', kind: 'registered', surface: 'flyout', tint: '--oc-cyan', order: -100, parts: { body: { component: FlyoutBodyFixture } } });
  const entries = railEntries(registry);
  expect(entries.fixed.map((w) => w.id)).toEqual([MENU_FLYOUT, SESSION_LIST_WIDGET]);
  expect(entries.registered[0]?.id).toBe('x.first');
});

test('T14: no docking or width control is offered on the rail or a slide-out', async () => {
  await railOn();
  await askOne();
  await press(QUESTIONS_FLYOUT);
  for (const root of [rail(), document.getElementById(FLYOUT_CONTAINER_ID)!]) {
    expect(root.querySelector('[role="separator"], [data-dock], [data-resize], [aria-label*="dock"], [aria-label*="width"]')).toBeNull();
  }
});

test('every slide-out declares an --oc-* tint and its title row is washed in it, with no border', async () => {
  const registry = new SidebarWidgetRegistry();
  registerCoreSidebarWidgets(registry);
  registerSwarmFlyout(registry);
  const tints = Object.fromEntries(registry.all().filter((w) => w.surface === 'flyout').map((w) => [w.id, w.tint]));
  expect(tints).toEqual({ [MENU_FLYOUT]: '--oc-text-muted', [QUESTIONS_FLYOUT]: '--oc-yellow', [SWARM_FLYOUT]: '--oc-green' });
  await railOn();
  await press(SWARM_FLYOUT);
  expect(flyout().style.getPropertyValue('--sbr-tint')).toBe('var(--oc-green)');
  const source = fs.readFileSync(path.join(REPO, 'web', 'src', 'lib', 'sidebar-widgets', 'SidebarFlyoutHost.svelte'), 'utf8');
  const titleCss = fs.readFileSync(path.join(REPO, 'web', 'src', 'lib', 'sidebar-widgets', 'flyout-title.css'), 'utf8');
  expect(source).toContain("import './flyout-title.css'");
  const css = `${source.slice(source.indexOf('<style>'))}\n${titleCss}`;
  expect(css).toMatch(/color-mix\(in srgb, var\(--sbr-tint\) 16%, transparent\)/);
  expect(css).not.toMatch(/\bborder(-(top|right|bottom|left|width|style|color))?\s*:/);
  expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(/i);
});

test('Escape is never claimed with no slide-out open', async () => {
  await railOn();
  const key = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
  railBtn(SESSION_LIST_WIDGET).dispatchEvent(key);
  expect(key.defaultPrevented).toBe(false);
});

test('a pick of the questions or huddle tab elsewhere opens its slide-out; the shell\'s move to menu does not', async () => {
  await railOn();
  sidebarTabs.select('menu');
  expect(redirectTabToFlyout('menu')).toBe(true);
  expect(sidebarTabs.active()).toBe('agents');
  expect(activeFlyout()).toBeNull();
  sidebarTabs.select(HUDDLE);
  redirectTabToFlyout(HUDDLE);
  expect(sidebarTabs.active()).toBe('agents');
  expect(activeFlyout()).toBe(SWARM_FLYOUT);
  expect(railHostsTab(HUDDLE)).toBe(true);
});

test('stats: hidden by default; when on it sits above the region, never under a slide-out', async () => {
  expect(statsShown()).toBe(false);
  await railOn();
  await askOne();
  expect(statsShown()).toBe(false);
  store[PREFERENCE_FIELD] = true;
  initStats();
  await press(QUESTIONS_FLYOUT);
  const stats = document.getElementById(DRAWER_STATS_ID)!;
  expect(statsShown()).toBe(true);
  expect(document.getElementById(REGION_ID)!.contains(stats)).toBe(false);
  expect(stats.nextElementSibling?.id).toBe(REGION_ID);
});

test('a stored sidebar_layout of classic still draws the rail, and nothing writes the field', async () => {
  store.sidebar_layout = 'classic';
  await railOn();
  expect(document.body.classList.contains(RAIL_BODY_CLASS)).toBe(true);
  expect(rail().querySelector('.sbr-rail')).not.toBeNull();
  expect(store.sidebar_layout).toBe('classic');
});

test('hidden until data: the questions icon is off the rail at zero and on it at one, and leaves again at zero', async () => {
  await railOn();
  expect(rail().querySelector(`[data-rail-widget="${QUESTIONS_FLYOUT}"]`)).toBeNull();
  await askOne();
  expect(railBtn(QUESTIONS_FLYOUT)).not.toBeNull();
  approvals.items = [];
  await settle();
  expect(rail().querySelector(`[data-rail-widget="${QUESTIONS_FLYOUT}"]`)).toBeNull();
  for (const id of [SESSION_LIST_WIDGET, SWARM_FLYOUT]) expect(railBtn(id), `${id} is always shown`).not.toBeNull();
});

test('hidden until data: an open questions slide-out closes back to agents when the last question goes', async () => {
  await railOn();
  await askOne();
  await press(QUESTIONS_FLYOUT);
  expect(activeFlyout()).toBe(QUESTIONS_FLYOUT);
  Element.prototype.animate ??= function animate(): Animation { return { finished: Promise.resolve(), cancel() {}, onfinish: null } as unknown as Animation; };
  approvals.items = [];
  await settle();
  expect(activeFlyout()).toBeNull();
  expect(railBtn(SESSION_LIST_WIDGET).getAttribute('aria-pressed')).toBe('true');
});

test('hidden until data: a widget with no data cannot be opened from anywhere (a toast pick of its tab)', async () => {
  await railOn();
  expect(openFlyout(QUESTIONS_FLYOUT)).toBe(false);
  await askOne();
  expect(openFlyout(QUESTIONS_FLYOUT)).toBe(true);
});

test('hidden until data: a number or a boolean source both gate; zero and false hide, positive and true show', () => {
  const base = { id: 'x.w', titleKey: 'k', icon: 'bot', kind: 'registered', surface: 'flyout', tint: '--oc-cyan', order: 1, parts: {} } as const;
  expect(widgetPresent({ ...base, hiddenUntilData: () => 0 })).toBe(false);
  expect(widgetPresent({ ...base, hiddenUntilData: () => 3 })).toBe(true);
  expect(widgetPresent({ ...base, hiddenUntilData: () => false })).toBe(false);
  expect(widgetPresent({ ...base, hiddenUntilData: () => true })).toBe(true);
  expect(widgetPresent({ ...base, hiddenUntilData: () => 3, present: () => false })).toBe(false);
});

function escapeFrom(target: EventTarget): KeyboardEvent {
  const key = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
  target.dispatchEvent(key);
  return key;
}

test('Escape closes an open slide-out only while focus is inside it or on the rail, never from the main pane or the terminal', async () => {
  await railOn();
  const term = document.createElement('textarea');
  term.className = 'xterm-helper-textarea';
  const screen = document.createElement('div');
  screen.className = 'xterm';
  screen.append(term);
  document.body.append(screen);
  await press(SWARM_FLYOUT);
  for (const from of [document.getElementById('main-target')!, term, document.body]) {
    const key = escapeFrom(from);
    await settle();
    expect(activeFlyout(), `Escape from ${from.tagName}.${from.className} leaves it open`).toBe(SWARM_FLYOUT);
    expect(key.defaultPrevented, 'and does not claim the key').toBe(false);
  }
  escapeFrom(flyout().querySelector<HTMLElement>('[data-flyout-close]')!);
  await settle();
  expect(activeFlyout(), 'a PINNED rail keeps its slide-out on an Escape from inside it').toBe(SWARM_FLYOUT);
  await unpinRail();
  escapeFrom(flyout().querySelector<HTMLElement>('[data-flyout-close]')!);
  await settle();
  expect(activeFlyout(), 'an unpinned one closes it from inside the slide-out').toBeNull();
});

test('with a slide-out and a menu page both open, Escape from the page closes the page and from the slide-out closes the slide-out', async () => {
  await railOn();
  await unpinRail();
  await press(SWARM_FLYOUT);
  const closePage = vi.fn();
  const stop = initMenuPageEscape(document, { pageOpen: () => true, close: closePage });
  const inside = escapeFrom(flyout().querySelector<HTMLElement>('[data-flyout-close]')!);
  await settle();
  expect(activeFlyout()).toBeNull();
  expect(closePage, 'the slide-out took the Escape that came from it').not.toHaveBeenCalled();
  expect(inside.defaultPrevented).toBe(true);
  await press(SWARM_FLYOUT);
  escapeFrom(document.getElementById('main-target')!);
  expect(closePage, 'the page takes an Escape from the main pane').toHaveBeenCalledTimes(1);
  expect(activeFlyout(), 'and the slide-out stays').toBe(SWARM_FLYOUT);
  stop();
});


const railKeys = (): HTMLButtonElement[] => [...rail().querySelectorAll<HTMLButtonElement>('.sbr-rail__btn')];
async function keyOn(el: Element, key: string): Promise<KeyboardEvent> {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  el.dispatchEvent(event);
  await settle();
  return event;
}

test('gap 1: a plugin tab with no slide-out of its own gets a rail key that opens its body (generic, not flow-only)', async () => {
  await railOn();
  const flowKey = tabFlyoutId(FLOW_TAB);
  expect(rail().querySelector(`[data-rail-widget="${flowKey}"]`), 'the tab is not present: no key').toBeNull();
  tabFlags.flow = true;
  await settle();
  const ids = [...rail().querySelectorAll<HTMLElement>('[data-rail-key]')].map((el) => el.dataset.railKey);
  expect(ids.slice(0, 3), 'after swarm; the huddle tab (swarm owns it) gets no second key').toEqual([SESSION_LIST_WIDGET, SWARM_FLYOUT, flowKey]);
  expect(ids.at(-1), 'settings stays last').toBe('settings');
  expect(ids.filter((id) => id === HUDDLE || id === tabFlyoutId(HUDDLE))).toEqual([]);
  await press(flowKey);
  expect(activeFlyout()).toBe(flowKey);
  expect(flyout().dataset.flyout).toBe(flowKey);
  expect(flyout().querySelector('.sbr-flyout__name')!.textContent).toBe('edit layout');
  expect(flyout().querySelector('[data-fixture-dropdown]'), "the tab body is the tab's own component").not.toBeNull();
  expect(railHostsTab(FLOW_TAB), 'the drawer\'s tab body region leaves it out so one copy runs').toBe(true);
  await press(flowKey);
  expect(activeFlyout()).toBeNull();
});

test('gap 1: the tab going away closes its slide-out; a pick of the tab elsewhere opens it and leaves the drawer on agents', async () => {
  await railOn();
  tabFlags.flow = true;
  await settle();
  sidebarTabs.select(FLOW_TAB);
  expect(redirectTabToFlyout(FLOW_TAB)).toBe(true);
  await settle();
  expect(activeFlyout()).toBe(tabFlyoutId(FLOW_TAB));
  expect(sidebarTabs.active()).not.toBe(FLOW_TAB);
  tabFlags.flow = false;
  await settle();
  expect(activeFlyout()).toBeNull();
});

test('a tab\'s main-area view lies over the main area only while its slide-out is open: no tab, gone on close, on a switch, and back on reopen', async () => {
  await railOn();
  tabFlags.flow = true;
  await settle();
  const flowKey = tabFlyoutId(FLOW_TAB);
  const view = (): Element | null => document.querySelector('#plugin-main-view [data-plugin-main-view] [data-main-fixture]');
  expect(view(), 'closed: nothing over the main area').toBeNull();
  const main = document.getElementById('main-pane')!;
  const before = main.innerHTML;
  await press(flowKey);
  expect(view(), 'open: the view is up').not.toBeNull();
  expect(document.querySelector('[data-browser-tab], #browser-screen'), 'it is no browser tab').toBeNull();
  expect(railBtn(flowKey), 'the rail key stays drawn').not.toBeNull();
  await press(flowKey);
  expect(view(), 'the key toggled off takes it down').toBeNull();
  expect(main.innerHTML, 'the main area is as it was').toBe(before);
  await press(flowKey);
  expect(view()).not.toBeNull();
  await press(SWARM_FLYOUT);
  expect(view(), 'another slide-out opening takes it down').toBeNull();
  await press(flowKey);
  flyout().querySelector<HTMLButtonElement>('[data-flyout-close]')!.click();
  await settle();
  expect(view(), 'the X takes it down').toBeNull();
});

test('gap 3: the rail keys are one tab stop (roving), and the arrows, Home and End walk them without opening anything', async () => {
  await railOn();
  const keys = railKeys();
  const at = (): string | undefined => (document.activeElement as HTMLElement).dataset.railKey;
  expect(keys.filter((k) => k.tabIndex === 0).map((k) => k.dataset.railKey), 'the first key (agents) is the stop').toEqual([SESSION_LIST_WIDGET]);
  railBtn(SESSION_LIST_WIDGET).focus();
  await keyOn(document.activeElement!, 'ArrowDown');
  expect(at()).toBe(SWARM_FLYOUT);
  await keyOn(document.activeElement!, 'End');
  expect(at()).toBe('settings');
  await keyOn(document.activeElement!, 'ArrowDown');
  expect(at(), 'wraps to the first').toBe(SESSION_LIST_WIDGET);
  await keyOn(document.activeElement!, 'ArrowUp');
  expect(at(), 'wraps to the last').toBe('settings');
  await keyOn(document.activeElement!, 'Home');
  expect(at()).toBe(SESSION_LIST_WIDGET);
  expect(railKeys().filter((k) => k.tabIndex === 0), 'still exactly one tab stop, now the focused key').toEqual([document.activeElement]);
  expect(activeFlyout(), 'moving focus opens nothing').toBeNull();
});

test('gap 3: Enter or Space (a click with no pointer) opens the focused key and moves focus into the slide-out; a pinned rail\'s Escape leaves it open', async () => {
  await railOn();
  railBtn(SWARM_FLYOUT).focus();
  railBtn(SWARM_FLYOUT).click();
  await settle();
  expect(activeFlyout()).toBe(SWARM_FLYOUT);
  expect((document.activeElement as HTMLElement).hasAttribute('data-flyout-close')).toBe(true);
  const esc = await keyOn(document.activeElement!, 'Escape');
  expect(esc.defaultPrevented, 'a pinned rail\'s slide-out keeps its Escape').toBe(false);
  expect(activeFlyout()).toBe(SWARM_FLYOUT);
});

test('gap 3: the menu hotkeys fire from any rail key (the menu has no key of its own, #2047)', async () => {
  vi.stubGlobal('SessionSidebarPin', { closeAfterSwitch: vi.fn() });
  await railOn();
  railBtn(SESSION_LIST_WIDGET).focus();
  const event = await keyOn(railBtn(SESSION_LIST_WIDGET), 'h');
  expect(event.defaultPrevented, 'a menu hotkey was handled').toBe(true);
});

test('gap 4: a question arriving brightens its rail key for a moment; keys whose count did not grow stay quiet', async () => {
  await railOn();
  await askOne();
  expect(railBtn(QUESTIONS_FLYOUT).querySelector<HTMLElement>('[data-rail-badge]')?.dataset.cue, 'the one badge pulses').toBe('on');
  expect(railBtn(SESSION_LIST_WIDGET).querySelector('[data-rail-badge]'), 'a key with no count wears no badge').toBeNull();
});

test("gap 4: a closable tab's key carries a close key, and Delete on the key closes it as in the tab strip", async () => {
  await railOn();
  tabFlags.closable = true;
  await settle();
  const id = tabFlyoutId(CLOSABLE_TAB);
  const closeBtn = rail().querySelector<HTMLButtonElement>(`[data-rail-close="${id}"]`);
  expect(closeBtn, "a close key on the closable tab's key").not.toBeNull();
  expect(rail().querySelector(`[data-rail-close="${SWARM_FLYOUT}"]`), 'a tab with no close has none').toBeNull();
  expect(closeBtn!.getAttribute('aria-label')).toBe('close edit layout');
  closeBtn!.click();
  await settle();
  expect(closedTabs).toEqual([CLOSABLE_TAB]);
  expect(rail().querySelector(`[data-rail-widget="${id}"]`), 'the key leaves with the tab').toBeNull();
  tabFlags.closable = true;
  await settle();
  railBtn(id).focus();
  const del = await keyOn(railBtn(id), 'Delete');
  expect(del.defaultPrevented).toBe(true);
  expect(closedTabs).toEqual([CLOSABLE_TAB, CLOSABLE_TAB]);
});
