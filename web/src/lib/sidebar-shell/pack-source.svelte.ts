import { packMachines, type PackMachine } from '../pack-machines/pack-machines-store.svelte';
import { repaintDrawerRows } from './interaction-globals';
import { packStats } from './pack-stats';

export function packSource(): PackMachine[] {
    return packMachines.data?.machines ?? [];
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
                    r?.level, r?.cpu_pct, r?.mem_pct, m.specs];
            }),
        ));
        $effect(() => {
            void signature;
            if (first) { first = false; return; }
            repaintDrawerRows();
        });
    });
}
