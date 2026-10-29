import type { InstalledItem } from '../catalog/types';

export interface Caller {
    handle: string;
    verb: 'installed' | 'updated';
    item: string;
    /* could not be read */
    computer: string | null;
    date: string;
}

interface LedgerStamps {
    installed_at?: string | null;
    updated_at?: string | null;
}

const stamp = (r: InstalledItem): { at: number; installed: number; updated: number } => {
    const s = r as InstalledItem & LedgerStamps;
    const installed = Date.parse(s.installed_at ?? '');
    const updated = Date.parse(s.updated_at ?? '');
    const i = Number.isFinite(installed) ? installed : 0;
    const u = Number.isFinite(updated) ? updated : 0;
    return { at: Math.max(i, u), installed: i, updated: u };
};

export function mmdd(ms: number): string {
    const d = new Date(ms);
    return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
}

export function lastCallers(ledger: readonly InstalledItem[], handle: string, computer: string | null, cap = 5): Caller[] {
    return ledger
        .map((r) => ({ r, s: stamp(r) }))
        .sort((a, b) => b.s.at - a.s.at)
        .slice(0, cap)
        .map(({ r, s }) => ({
            handle,
            verb: s.installed === s.updated ? ('installed' as const) : ('updated' as const),
            item: String(r.name ?? r.item_id ?? ''),
            computer,
            date: s.at ? mmdd(s.at) : '',
        }));
}
