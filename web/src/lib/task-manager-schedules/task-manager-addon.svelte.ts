import manifest from '../../../../src/cplugs/huddle/cplug.json';
import { cplugEnabled } from '../../cplugs/host/enablement.svelte';
import type { CplugManifest } from '../../cplugs/sdk';

export function taskManagerAddonOn(): boolean {
  return cplugEnabled(manifest as CplugManifest);
}
