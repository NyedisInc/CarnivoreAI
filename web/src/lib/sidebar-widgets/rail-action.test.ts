/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async () => ({ v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [], machines: [] }),
}));
const openPage = vi.hoisted(() => vi.fn(async () => undefined));
vi.mock('../browser/select-push.svelte', async (original) => ({ ...(await original<Record<string, unknown>>()), openPage }));

import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import { cplugTabs } from '../../cplugs/host/readers';
import { devwidgetlabCplug } from '../../cplugs/devwidgetlab';
import { SELECTION_KEY } from '../../cplugs/devwidgetlab/lab-selection';
import { installLabBus } from '../../cplugs/devwidgetlab/lab-test-bus';
import { registerTab, tabRegistry } from '../dynamic-tabs/registry';
import { setLocale } from '../i18n/index.svelte';
import { activeFlyout, closeFlyout } from './flyout.svelte';
import { railOn, railBtn, rail, flyout, press, setupRail, settle, teardownRail } from './fixtures/rail-harness';
import { tabFlyoutId } from './tab-flyouts';
import FlyoutBodyFixture from './fixtures/FlyoutBodyFixture.svelte';

setLocale('en');

const KEY = tabFlyoutId('devwidgetlab');
const keyOnRail = (): Element | null => rail().querySelector(`[data-rail-widget="${KEY}"]`);

beforeEach(async () => {
  await setupRail();
  for (const def of cplugTabs([devwidgetlabCplug])) if (!tabRegistry.get(def.id)) registerTab({ ...def, order: 45 });
  openPage.mockClear();
  installLabBus();
  cplugEnablement.enabled = {};
});

afterEach(teardownRail);

test('the lab key is in the rail while the plugin is on, gone while it is off', async () => {
  cplugEnablement.enabled = { devwidgetlab: false };
  await railOn();
  expect(keyOnRail(), 'plugin off: no key').toBeNull();
  cplugEnablement.enabled = { devwidgetlab: true };
  await settle();
  const key = keyOnRail();
  expect(key, 'plugin on: the key is drawn').not.toBeNull();
  expect(key!.querySelector('svg'), 'with its icon').not.toBeNull();
  expect(key!.getAttribute('aria-label')).toBe('widget lab');
  cplugEnablement.enabled = { devwidgetlab: false };
  await settle();
  expect(keyOnRail(), 'switched off again: the key leaves').toBeNull();
});

const viewer = (): Element | null => document.querySelector('#plugin-main-view .dwl');

test('the lab viewer lies over the main area while its slide-out is open, with no tab; closing the slide-out restores the area, and reopening restores the pick', async () => {
  cplugEnablement.enabled = { devwidgetlab: true };
  await railOn();
  const main = document.getElementById('main-pane')!;
  const before = main.innerHTML;
  await press(KEY);
  await settle();
  expect(activeFlyout(), 'the slide-out opened').toBe(KEY);
  expect(flyout().querySelector('.sbr-flyout__name')?.textContent).toBe('widget lab');
  expect(flyout().querySelector('.dwl-menu'), 'with the lab menu as its body').not.toBeNull();
  expect(viewer(), 'the viewer is over the main area').not.toBeNull();
  expect(openPage, 'no browser tab or page is opened').not.toHaveBeenCalled();
  expect(document.querySelector('.dwl-strip')!.textContent, 'no "widget lab" page title').not.toMatch(/widget lab/i);
  const pick = flyout().querySelector<HTMLButtonElement>('.dwl-leaf[data-key]:not([data-key="core.notes"])')!;
  pick.click();
  await settle();
  const picked = JSON.parse(localStorage.getItem(SELECTION_KEY)!).selection.widget as string;
  expect(picked).not.toBe('core.notes');
  closeFlyout();
  await settle();
  expect(activeFlyout()).toBeNull();
  expect(viewer(), 'closing the slide-out closes the viewer').toBeNull();
  expect(main.innerHTML, 'the main area shows what it showed before').toBe(before);
  expect(keyOnRail(), 'the key stays after the slide-out closes').not.toBeNull();
  await press(KEY);
  await settle();
  expect(viewer(), 'reopening brings it back').not.toBeNull();
  expect(document.querySelector('.dwl-strip-name')!.textContent).toBe(
    flyout().querySelector('.dwl-leaf[aria-current="true"] .dwl-leaf-name')!.textContent,
  );
  expect(JSON.parse(localStorage.getItem(SELECTION_KEY)!).selection.widget).toBe(picked);
});

test('a tab with a railAction still runs it and opens no slide-out', async () => {
  const run = vi.fn();
  registerTab({ id: 'action-test', labelKey: 'cplug.devwidgetlab.tab', icon: 'grid', order: 47, persist: false, widgetArea: 'closed', railAction: run, body: { component: FlyoutBodyFixture } });
  await railOn();
  await press(tabFlyoutId('action-test'));
  expect(run).toHaveBeenCalledTimes(1);
  expect(activeFlyout(), 'no slide-out opened').toBeNull();
  expect(railBtn(tabFlyoutId('action-test')).hasAttribute('aria-pressed'), 'an action key is never pressed').toBe(false);
});
