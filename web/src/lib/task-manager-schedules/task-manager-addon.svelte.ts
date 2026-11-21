import manifest from '../../../../src/plugins/huddle/cplug.json';
import { cplugEnabled } from '../../plugins/host/enablement.svelte';
import type { CplugManifest } from '../../plugins/sdk';

export function taskManagerAddonOn(): boolean {
  return cplugEnabled(manifest as CplugManifest);
}
