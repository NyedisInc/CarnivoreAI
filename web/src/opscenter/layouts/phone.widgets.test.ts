/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { terminalLayout } from '../engine/layout.svelte';
import { resetTabCache, setGroups } from '../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../engine/model';
import { widgetTabId } from '../engine/widget-tabs';
import { phoneTabSource } from './phone.svelte';

afterEach(() => {
  resetTabCache();
  localStorage.clear();
});

test('the phone strip lists the sessions of the pane component and leaves widget tabs out', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, widgetTabId('core.tasks'), 'terminal:ses_b'] } });
  expect(phoneTabSource.tabs()).toEqual([PRIMARY_SLOT, 'terminal:ses_b']);
});
