import { setPanels } from '../lib/cplug-ui/panel-views.svelte';
import { PANEL_TAIL } from '../opscenter/cells/plugin-view/constants';
import type { CplugRow } from '../lib/plugins-page/cplugs-adapter';
import type { SlotId } from '../opscenter/engine/types';

export const FIXTURE_PLUGIN_ID = 'fx-plugin';
export const FIXTURE_VIEW = 'demo';

export const FIXTURE_KIND = `${FIXTURE_PLUGIN_ID}.${FIXTURE_VIEW}`;

const FIXTURE_INSTALL_KEY = 'fixture1';

export const FIXTURE_SLOT = `${FIXTURE_KIND}:${PANEL_TAIL}-${FIXTURE_INSTALL_KEY}` as SlotId;

export const FIXTURE_VIEW_PATH = '/__plugin-view-fixture__/index.html';

const FIXTURE_FITS = { sizes: ['tall', 'medium', 'large', 'full'], anySize: true, min: { w: 2, h: 4 } };

function fixtureRow(on: boolean): CplugRow {
  return {
    id: FIXTURE_PLUGIN_ID, runtime: 'sidecar', enabled: on, state: on ? 'active' : 'stopped', name: 'fx-plugin',
    install_key: FIXTURE_INSTALL_KEY, unverified: true,
    views: [{ name: FIXTURE_VIEW, surfaces: ['panel'], fits: FIXTURE_FITS }],
  } as unknown as CplugRow;
}

export function registerPluginViewFixture(on = true): void {
  setPanels([fixtureRow(true)]);
  if (!on) setPanels([fixtureRow(false)]);
}
