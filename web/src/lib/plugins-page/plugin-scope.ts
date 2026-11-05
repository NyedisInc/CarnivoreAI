import { isBuiltinPlugin, isFeatureTier } from '../catalog/app-own';
import { featureRows } from './feature-words';
import { hasPluginSettings } from './plugin-settings-link';
import { settingsFeatureFragment, settingsPluginFragment } from '../settings-page/settings-hash';
import type { CplugItem } from './cplugs-adapter';

export type PageScope = 'features' | 'plugins' | undefined;

export interface ScopeRules {
    scope: PageScope;
    developerMode: boolean;
    storeOnly: boolean;
}

export function rowsInScope(rows: readonly CplugItem[], rules: ScopeRules): CplugItem[] {
    if (rules.scope === 'features') return featureRows(rows, rules.developerMode);
    if (rules.scope === 'plugins') return rows.filter((row) => !isFeatureTier(row.tier));
    return rows.filter((row) => !rules.storeOnly || !isBuiltinPlugin(row.tier));
}

export function featureHandOffFragment(row: CplugItem, wantsSettings: boolean): string {
    return wantsSettings && row.enabled === true && hasPluginSettings(row) ? settingsPluginFragment(row.cplugId) : settingsFeatureFragment(row.cplugId);
}

export function replaceHashWith(fragment: string): void {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${fragment}`);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
}
