import manifest from '../../../../src/cplugs/argent/cplug.json';
import type { Component } from 'svelte';
import type { CplugManifest, CplugWeb, Contribution } from '../sdk';
import ArgentSettings from './ArgentSettings.svelte';

export const SETTINGS_PANEL_ID = 'argent';

const settingsPanel: Contribution<'settings-panel'> = {
  id: SETTINGS_PANEL_ID,
  surface: 'settings-panel',
  enabled: () => true,
  payload: { Panel: ArgentSettings as unknown as Component<Record<string, never>> },
};

export const argentCplug: CplugWeb = {
  id: 'argent',
  manifest: manifest as CplugManifest,
  plugins: [settingsPanel as unknown as Contribution],
};
