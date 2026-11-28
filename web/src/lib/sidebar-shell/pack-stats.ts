import { cpuPercent } from '../pack-machines/pack-meter-math';
import type { MeshLink } from '../computers/computers-api';
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
    return { cpu: cpuPercent(load), ram: load.memory_percent ?? null, disk: load.disk_percent ?? null };
}

export function averagePackStats(machines: ReadonlyArray<Pick<PackMachine, 'snapshot'>>): PackStats {
    const avg = (vals: number[]): number | null =>
        vals.length ? Math.round(vals.reduce((sum, v) => sum + v, 0) / vals.length) : null;
    const readings = machines.map((m) => packStats(m));
    return {
        cpu: avg(readings.flatMap((s) => (s.cpu !== null && Number.isFinite(s.cpu) ? [s.cpu] : []))),
        ram: avg(readings.flatMap((s) => (s.ram !== null && Number.isFinite(s.ram) ? [s.ram] : []))),
        disk: avg(readings.flatMap((s) => (s.disk !== null && Number.isFinite(s.disk) ? [s.disk] : []))),
    };
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

const KNOWN_STATES = ['stale', 'waiting', 'older', 'not_paired', 'disconnected', 'connecting', 'unknown', 'reported_connected', 'reported_disconnected', 'reported_connecting'];

const DIAL = ['linked', 'dialing', 'unreachable', 'refused', 'local_network_blocked', 'cert_mismatch', 'held_over', 'excluded', 'not_held'];

export function stateWord(state: string, link?: MeshLink | null, relayerUp = true): string {
    const word = state.startsWith('reported_') && !relayerUp ? 'unknown' : state;
    const base = t(KNOWN_STATES.includes(word) ? `pack.machines.state.${word}` : 'pack.machines.state.unknown');
    if (!link || !DIAL.includes(link.state)) return base;
    const direct = t(`roster.dial.${link.state}`);
    return word === 'reported_connected' ? `${base}, ${direct}` : direct;
}

export function relayerReachable(machines: ReadonlyArray<Pick<PackMachine, 'is_master' | 'state'>>): boolean {
    const alpha = machines.find((m) => m.is_master);
    return !alpha || alpha.state === 'self' || alpha.state === 'connected';
}

export function countOnline(machines: readonly PackMachine[], linkOf: (m: PackMachine) => MeshLink | null): number {
    return machines.filter((m) => ['connected', 'self', 'reported_connected'].includes(m.state) || linkOf(m)?.state === 'linked').length;
}
