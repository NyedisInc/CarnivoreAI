import { isBuiltinPlugin, isFeatureTier } from '../catalog/app-own';
import { featureRows } from './feature-words';
import type { CplugItem } from './cplugs-adapter';

export type PageScope = 'features' | 'plugins' | undefined;

export interface ScopeRules {
    scope: PageScope;
    developerMode: boolean;
    storeOnly: boolean;
}

export function rowsInScope(rows: readonly CplugItem[], rules: ScopeRules): CplugItem[] {
    if (rules.scope === 'features') return featureRows(rows, rules.developerMode);
    if (rules.storeOnly) return rows.filter((row) => !isFeatureTier(row.tier));
    if (rules.scope === 'plugins') return rows.filter((row) => row.tier !== 'dev' || rules.developerMode);
    return [...rows];
}

export function replaceHashWith(fragment: string): void {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${fragment}`);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
}
