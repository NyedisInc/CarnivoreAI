import { loadPercent } from '../pack-machines/pack-meter-math';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';
import { t } from '../i18n/index.svelte';

export interface PackStats {
    cpu: number | null;
    ram: number | null;
    disk: number | null;
}

export function packStats(m: Pick<PackMachine, 'snapshot'>): PackStats {
    const load = m.snapshot?.load;
    if (!load) return { cpu: null, ram: null, disk: null };
    return { cpu: loadPercent(load.load_1, load.cores), ram: load.memory_percent ?? null, disk: load.disk_percent ?? null };
}

export function percentText(pct: number | null): string {
    return pct === null || !Number.isFinite(pct) ? '-' : `${Math.round(pct)}%`;
}

export function specLine(m: Pick<PackMachine, 'specs' | 'snapshot'>): string {
    const s = m.specs;
    const parts: string[] = [];
    if (s?.model) parts.push(s.model);
    if (typeof s?.cores === 'number') parts.push(t('drawer.pack.cores', { count: s.cores }));
    if (typeof s?.mem_total_gb === 'number') parts.push(t('drawer.pack.memory', { gb: s.mem_total_gb }));
    const r = m.snapshot?.reserve;
    if (r && (r.level === 'in_use' || r.level === 'away')) {
        parts.push(t(`drawer.pack.reserve.${r.level}`, { cpu: r.cpu_pct, mem: r.mem_pct }));
    }
    return parts.join(' ');
}

const KNOWN_STATES = ['stale', 'waiting', 'older', 'not_paired', 'disconnected', 'connecting'];

export function stateWord(state: string): string {
    return t(KNOWN_STATES.includes(state) ? `pack.machines.state.${state}` : 'drawer.pack.state.offline');
}
