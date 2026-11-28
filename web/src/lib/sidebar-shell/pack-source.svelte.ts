import { packMachines, type PackMachine } from '../pack-machines/pack-machines-store.svelte';
import type { ComputersView, MeshLink } from '../computers/computers-api';
import { meshOn } from '../pack-roster/roster-model';
import { repaintDrawerRows } from './interaction-globals';
import { packStats } from './pack-stats';

export function packSource(): PackMachine[] {
    return packMachines.data?.machines ?? [];
}

let meshStore = $state<{ data: ComputersView | null } | null>(null);

export function meshLinkOf(m: PackMachine): MeshLink | null {
    if (!meshOn(packMachines.data) || m.paired || m.is_self) return null;
    return meshStore?.data?.mesh?.links.find((l) => l.install_id === m.install_id) ?? null;
}

let stopWatching: (() => void) | null = null;

export function watchPack(): void {
    if (stopWatching) return;
    let first = true;
    stopWatching = $effect.root(() => {
        const signature = $derived(JSON.stringify(
            packSource().map((m) => {
                const s = packStats(m);
                const r = m.snapshot?.reserve;
                return [m.install_id, m.label, m.is_self, m.is_master, m.state, s.cpu === null ? null : Math.round(s.cpu),
                    s.ram === null ? null : Math.round(s.ram), s.disk === null ? null : Math.round(s.disk),
                    r?.level, r?.cpu_pct, r?.mem_pct, m.specs, ...(meshOn(packMachines.data) ? [meshLinkOf(m)?.state] : [])];
            }),
        ));
        $effect(() => {
            if (meshOn(packMachines.data) && meshStore === null) void import('../computers/computers-store.svelte').then((mod) => { meshStore = mod.computers; });
        });
        $effect(() => {
            void signature;
            if (first) { first = false; return; }
            repaintDrawerRows();
        });
    });
}
