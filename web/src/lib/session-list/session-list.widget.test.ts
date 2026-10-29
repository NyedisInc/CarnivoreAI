/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { mountPanel, unmountPanel } from '../mount';
import { setLocale, t } from '../i18n/index.svelte';
import * as Density from '../drawer/density';
import { DRAWER_LIST_ID } from '../drawer-tabs/drawer-tabs';
import { declaredActionsFor } from '../../opscenter/widgets/menu/declared-actions.svelte';
import { SESSION_LIST_WIDGET } from '../sidebar-widgets/widget-ids';
import { closeRailMenu } from '../sidebar-widgets/rail-menu.svelte';
import { editorSeams } from '../../opscenter/layout-editor/editor.svelte';
import { prefs, railBtn, railOn, settle, setupRail, teardownRail } from '../sidebar-widgets/fixtures/rail-harness';
import { ShellView } from '../sidebar-shell/shell.svelte';
import { ROOT_ZONE_KEY } from '../drawer-layout/root-zone.svelte';
import { VIEW_CHOICES } from './view-choices';
import SessionListWidget from './SessionListWidget.svelte';

setLocale('en');

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const g = globalThis as Record<string, unknown>;
const realSeams = { ...editorSeams };
const HEADER = `${ROOT_ZONE_KEY}#agents`;

async function mountList(): Promise<ShellView> {
  const view = new ShellView();
  view.plan = { leadHtml: '<p class="lead-line">lead</p>', parts: [], tailHtml: '<p class="tail-line">tail</p>' };
  mountPanel(DRAWER_LIST_ID, SessionListWidget, { view });
  await settle();
  return view;
}

beforeEach(async () => {
  editorSeams.wide = () => true;
  editorSeams.page = () => ({}) as never;
  editorSeams.store = () => ({}) as never;
  await setupRail();
  g.SessionSidebarDensity = Density;
});

afterEach(async () => {
  Object.assign(editorSeams, realSeams);
  closeRailMenu();
  unmountPanel(DRAWER_LIST_ID);
  delete g.SessionSidebarDensity;
  await teardownRail();
});

test('it draws the plan with no wrapper element and makes no request', async () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
  await mountList();
  const list = document.getElementById(DRAWER_LIST_ID)!;
  expect([...list.children].map((el) => el.className)).toEqual(['lead-line', 'tail-line']);
  expect(list.querySelector('.oc-wshell')).toBeNull();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test('it declares every view choice on the root zone tab header, in the menu order', async () => {
  await mountList();
  const declared = declaredActionsFor(HEADER);
  expect(declared.map((a) => a.id)).toEqual(VIEW_CHOICES.map((c) => c.id));
  expect(declared.find((a) => a.id === 'density-compact')!.checked).toBe(true);
  expect(declared.find((a) => a.id === 'show-stats')!.toggle).toBe(true);
});

test('a right-click on the agents key offers the declared view choices', async () => {
  await mountList();
  await railOn();
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 12, clientY: 20 });
  railBtn(SESSION_LIST_WIDGET).dispatchEvent(event);
  flushSync();
  const labels = [...document.querySelectorAll<HTMLElement>('.acm-menu [role^="menuitem"]')].map((el) => el.textContent?.trim() ?? '');
  for (const mode of ['compact', 'cozy', 'detailed']) expect(labels.some((l) => l.includes(t(`drawer.density.${mode}`)))).toBe(true);
  expect(labels.some((l) => l.includes(t('drawer.density.show_stats')))).toBe(true);
});

test('a density pick from the declared choices writes the field it always wrote and nothing else', async () => {
  await mountList();
  declaredActionsFor(HEADER).find((a) => a.id === 'density-detailed')!.run();
  await settle();
  expect(prefs.store).toEqual({ sidebar_density: 'detailed' });
  expect(declaredActionsFor(HEADER).find((a) => a.id === 'density-detailed')!.checked, 'the tick follows the pick').toBe(true);
});
