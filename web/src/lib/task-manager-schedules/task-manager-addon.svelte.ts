/* the Task Manager */
import manifest from '../../../../src/plugins/taskmanager/carnivore.toml';
import { cplugEnabled } from '../../plugins/host/enablement.svelte';
import type { CplugManifest } from '../../plugins/sdk';

/* the Task Manager */
export function taskManagerAddonOn(): boolean {
  return cplugEnabled(manifest as CplugManifest);
}
