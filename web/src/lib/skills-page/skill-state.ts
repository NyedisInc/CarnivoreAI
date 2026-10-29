/* could not */
import type { InstalledItem, SkillAutopsy } from '../catalog/types';
import type { Translate } from '../sessions/types';
import type { Census, SkillGroupRow } from './skills-types';

export type Tripwire = { readonly state: 'clean' } | { readonly state: 'flagged'; readonly categories: readonly string[] } | { readonly state: 'not_judged' };

export interface SkillHealthMap {
    /* could not be read */
    readonly ledger: readonly InstalledItem[] | null;
    /* could not be read */
    readonly census: Census | null;
    readonly tripwire: Readonly<Record<string, Tripwire>>;
}

export const NO_HEALTH: SkillHealthMap = { ledger: null, census: null, tripwire: {} };

export const AUTOPSY_CAP = 25;

export function ledgerRowsOf(group: SkillGroupRow, ledger: readonly InstalledItem[] | null): InstalledItem[] {
    if (!ledger) return [];
    const ids = new Set(group.locations.flatMap((l) => (l.managed?.item_id ? [l.managed.item_id] : [])));
    return ledger.filter((row) => row.item_id != null && ids.has(row.item_id));
}

export function tripwireOf(autopsy: SkillAutopsy | null): Tripwire {
    if (!autopsy || !Array.isArray(autopsy.undisclosed)) return { state: 'not_judged' };
    return autopsy.undisclosed.length > 0 ? { state: 'flagged', categories: autopsy.undisclosed } : { state: 'clean' };
}

export type MarkerId = 'drifted' | 'missing' | 'flagged' | 'unused';

export function markersOf(group: SkillGroupRow, health: SkillHealthMap): MarkerId[] {
    const out: MarkerId[] = [];
    const rows = ledgerRowsOf(group, health.ledger);
    if (rows.some((r) => r.drift?.state === 'drifted')) out.push('drifted');
    if (rows.some((r) => r.drift?.state === 'missing')) out.push('missing');
    if (health.tripwire[group.name]?.state === 'flagged') out.push('flagged');
    const fires = health.census?.skills.find((s) => s.name === group.name)?.fires ?? null;
    if (fires !== null && fires.d30 === 0) out.push('unused');
    return out;
}

export function markerWords(ids: readonly MarkerId[], t: Translate): string[] {
    return ids.map((id) => t(`skills.mark.${id}`));
}
