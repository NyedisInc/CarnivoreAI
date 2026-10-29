import type { ManagerController } from '../manager-frame/manager-controller.svelte';
import type { ManagerAdapter } from '../manager-frame/types';
import type { CplugItem, CplugsAdapter } from './cplugs-adapter';

export function createPluginActions(opts: {
    ctl: ManagerController;
    adapter: ManagerAdapter & Partial<CplugsAdapter>;
    grant: (cplugId: string, ticks: string[]) => Promise<unknown>;
    onAsk?: (id: string) => void;
}): {
    readonly pendingOff: string | null;
    request(id: string, next: boolean): void;
    confirm(): void;
    cancel(): void;
    grantFromSheet(plugin: CplugItem, ticks: string[]): Promise<void>;
} {
    const { ctl, adapter, grant, onAsk } = opts;
    let pendingOff = $state<string | null>(null);

    return {
        get pendingOff() { return pendingOff; },
        request(id, next): void {
            const item = ctl.items.find((row) => row.id === id) as CplugItem | undefined;
            if (!next && item?.enabled && (item.deps?.enabledDependents.length ?? 0) > 0) {
                pendingOff = id;
                onAsk?.(id);
                return;
            }
            void ctl.toggle(id, next);
        },
        confirm(): void {
            const id = pendingOff;
            pendingOff = null;
            if (!id) return;
            adapter.confirmDependents?.(id);
            void ctl.toggle(id, false);
        },
        cancel(): void {
            pendingOff = null;
        },
        async grantFromSheet(plugin, ticks): Promise<void> {
            if (!plugin.consentRequired) return ctl.toggle(plugin.id, true);
            await grant(plugin.cplugId, ticks);
            await ctl.load();
        },
    };
}
