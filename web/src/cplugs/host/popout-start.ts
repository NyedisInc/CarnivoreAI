/* list, so the */
import { POPOUT_CPLUGS } from '../popout';
import type { CplugPopout } from '../sdk';
import { cplugEnabled, followEnablement } from './enablement.svelte';

export function startPopoutEnabled(cplugs: readonly CplugPopout[] = POPOUT_CPLUGS): void {
  for (const part of cplugs) {
    if (!part.start || !cplugEnabled(part.manifest)) continue;
    try {
      part.start();
    } catch (err) {
      console.error(`cplug ${part.id}: pop-out start failed`, err);
    }
  }
}

export function startPopoutCplugs(): void {
  startPopoutEnabled();
  followEnablement(() => startPopoutEnabled());
}
