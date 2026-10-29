import manifest from '../../../../src/cplugs/save/cplug.json';
import type { Component } from 'svelte';
import type { CplugManifest, CplugWeb, Contribution, SessionTabSession } from '../sdk';
import SaveSettings from './SaveSettings.svelte';
import SessionTab from './SessionTab.svelte';

export const SETTINGS_PANEL_ID = 'save';
export const SESSION_TAB_ID = 'save-restore-points';

const settingsPanel: Contribution<'settings-panel'> = {
  id: SETTINGS_PANEL_ID,
  surface: 'settings-panel',
  enabled: () => true,
  payload: { Panel: SaveSettings as unknown as Component<Record<string, never>> },
};

const sessionTab: Contribution<'session-tab'> = {
  id: SESSION_TAB_ID,
  surface: 'session-tab',
  order: 100,
  enabled: () => true,
  payload: { labelKey: 'cplug.save.tab.name', Tab: SessionTab as unknown as Component<{ session: SessionTabSession }> },
};

export const saveCplug: CplugWeb = {
  id: 'save',
  manifest: manifest as CplugManifest,
  plugins: [settingsPanel as unknown as Contribution, sessionTab as unknown as Contribution],
};
