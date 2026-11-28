/* list, so the */
import { POPOUT_CPLUGS } from '../popout';
import type { CplugPopout } from '../sdk';
import { cplugEnabled, followEnablement } from './enablement.svelte';
import { setPanels } from '../../lib/cplug-ui/panel-views.svelte';
import { setPluginTabs } from '../../lib/cplug-ui/plugin-tabs.svelte';
import type { CplugRow } from '../../lib/plugins-page/cplugs-adapter';
import { pluginsStore, type StoreCplugRow } from '../../lib/plugins/store.svelte';

function applyPopoutPluginRows(rows: readonly StoreCplugRow[]): void {
  const cplugRows = rows as unknown as readonly CplugRow[];
  setPanels(cplugRows);
  setPluginTabs(cplugRows);
}

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

let runtimeBooted = false;

export function startPopoutCplugs(): void {
  startPopoutEnabled();
  followEnablement(() => startPopoutEnabled());
  if (!runtimeBooted) {
    runtimeBooted = true;
    pluginsStore.onRows((rows) => applyPopoutPluginRows(rows));
    if (pluginsStore.read) applyPopoutPluginRows(pluginsStore.rows);
    pluginsStore.acquire({ allowSignedOut: true, includeSlots: true });
  }
}
