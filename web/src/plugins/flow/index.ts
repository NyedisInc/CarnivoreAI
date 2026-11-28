import manifest from '../../../../src/plugins/flow/carnivore.toml';
import type { CplugManifest, CplugWeb } from '../sdk';
import { flowTab } from './flow-tab';
import { followFlowPrefs } from './flow-prefs.svelte';

export const flowCplug: CplugWeb = {
  id: 'flow',
  manifest: manifest as CplugManifest,
  tabs: [flowTab],
  start: followFlowPrefs,
};
