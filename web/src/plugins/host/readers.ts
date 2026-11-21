import { BUILTIN_CPLUGS } from '../builtin';
import { POPOUT_CPLUGS } from '../popout';
import type { AccountMenuItem, BarIndicator, CplugManifest, CplugWeb, Contribution, DynamicTabDef, RailItem } from '../sdk';
import type { Plugin, PluginContext, SessionCardRow } from '../../lib/plugins/types';
import { runSessionCardAction } from '../../lib/plugins/session-card-actions';
import { cplugEnabled, followEnablement } from './enablement.svelte';
import { registerEnabledWidgets } from './widgets';
import { registerPageSections } from '../../lib/drawer/page-sections';
import { thirdPartyBarIndicators } from '../../lib/cplug-ui/bar-indicators.svelte';

function gateTab(manifest: CplugManifest, def: DynamicTabDef): DynamicTabDef {
  const present = def.present;
  return { ...def, nameKey: def.nameKey ?? manifest.name_key, present: () => cplugEnabled(manifest) && (present ? present() : true) };
}

export function cplugTabs(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): DynamicTabDef[] {
  return cplugs.flatMap((a) => (a.tabs ?? []).map((def) => gateTab(a.manifest, def)));
}

export function cplugPopoutTabs(): DynamicTabDef[] {
  return POPOUT_CPLUGS.flatMap((a) => a.tabs.map((def) => gateTab(a.manifest, def)));
}

export function cplugPopoutTabsOn(): DynamicTabDef[] {
  return POPOUT_CPLUGS.flatMap((a) => (cplugEnabled(a.manifest) ? a.tabs.filter((def) => def.popout === true) : []));
}

export function cplugMenuLinks(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): RailItem[] {
  return cplugs.flatMap((a) => (a.menuLinks ?? []).map((item) => ({ ...item, visible: () => cplugEnabled(a.manifest) })));
}

export interface PluginAccountItem extends AccountMenuItem {
  cplugId: string;
}

export function cplugAccountMenuItems(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): PluginAccountItem[] {
  return cplugs.flatMap((a) => (cplugEnabled(a.manifest) ? (a.accountMenuItems ?? []) : [])
    .filter((item) => (item.visible ? item.visible() : true))
    .map((item) => ({ ...item, cplugId: a.id })));
}

export interface PluginBarIndicator extends BarIndicator {
  cplugId: string;
  action: string;
}

export const BAR_INDICATOR_ACTION = 'cplug:';

export function cplugBarIndicators(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): PluginBarIndicator[] {
  const compiled = cplugs.flatMap((a) => (cplugEnabled(a.manifest) ? (a.barIndicators ?? []) : [])
    .filter((item) => item.visible())
    .map((item) => ({ ...item, cplugId: a.id, action: `${BAR_INDICATOR_ACTION}${a.id}.${item.id}` })));
  const installed = cplugs === BUILTIN_CPLUGS
    ? thirdPartyBarIndicators().filter((item) => item.visible()).map((item) => ({ ...item, action: `${BAR_INDICATOR_ACTION}${item.cplugId}.${item.id}` }))
    : [];
  return [...compiled, ...installed];
}

export function cplugPlugins(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): Plugin[] {
  return cplugs
    .filter((a) => (a.plugins ?? []).length > 0)
    .map((a) => ({
      id: a.id,
      contributions: (a.plugins ?? []).map((c) => ({
        ...c,
        enabled: (context: Parameters<Contribution['enabled']>[0]) => cplugEnabled(a.manifest) && c.enabled(context),
      })) as Contribution[],
    }));
}

export async function runCplugCardAction(cplugId: string, row: SessionCardRow, context: PluginContext): Promise<boolean> {
  const action = BUILTIN_CPLUGS.find((a) => a.id === cplugId)?.plugins?.find((c) => c.surface === 'session-card-action');
  return action ? runSessionCardAction(action.id, row, context) : false;
}

export function startEnabled(cplugs: readonly CplugWeb[] = BUILTIN_CPLUGS): void {
  registerEnabledWidgets();
  for (const a of cplugs) {
    const on = cplugEnabled(a.manifest);
    try {
      if (on) a.start?.();
      else a.stop?.();
    } catch (err) {
      console.error(`cplug ${a.id}: ${on ? 'start' : 'stop'} failed`, err);
    }
  }
}

export function startCplugs(): void {
  startEnabled();
  followEnablement(startEnabled);
}

registerPageSections(BUILTIN_CPLUGS.flatMap((a) => {
  const s = a.manifest.surfaces;
  return s.page_section && s.page_section_label_key ? [{ id: s.page_section, labelKey: s.page_section_label_key, icon: s.page_section_icon ?? '' }] : [];
}));
