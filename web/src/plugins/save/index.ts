import manifest from '../../../../src/plugins/save/carnivore.toml';
import type { Component } from 'svelte';
import type { CplugManifest, CplugWeb, Contribution } from '../sdk';
import SaveSettings from './SaveSettings.svelte';

export const SETTINGS_PANEL_ID = 'save';

const settingsPanel: Contribution<'settings-panel'> = {
  id: SETTINGS_PANEL_ID,
  surface: 'settings-panel',
  enabled: () => true,
  payload: { Panel: SaveSettings as unknown as Component<Record<string, never>> },
};

export const saveCplug: CplugWeb = {
  id: 'save',
  manifest: manifest as CplugManifest,
  plugins: [settingsPanel as unknown as Contribution],
};
