import type { ManagerController } from '../manager-frame/manager-controller.svelte';
import type { ManagerAdapter } from '../manager-frame/types';
import type { CplugItem, CplugSheet, CplugsAdapter } from './cplugs-adapter';
import type { GrantOptions } from './cplug-grant';

export function createPluginActions(opts: {
    ctl: ManagerController;
    adapter: ManagerAdapter & Partial<CplugsAdapter>;
    grant: (cplugId: string, ticks: string[], options: GrantOptions) => Promise<unknown>;
    seenSheet?: (cplugId: string) => CplugSheet | undefined;
    onAsk?: (id: string) => void;
}): {
    readonly pendingOff: string | null;
    request(id: string, next: boolean): void;
    confirm(): void;
    cancel(): void;
    grantFromSheet(plugin: CplugItem, ticks: string[]): Promise<void>;
} {
    const { ctl, adapter, grant, seenSheet, onAsk } = opts;
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
            await ctl.guard(plugin.id, async () => {
                await grant(plugin.cplugId, ticks, { enable: !plugin.enabled, seen: seenSheet?.(plugin.cplugId) });
                await ctl.load();
            });
        },
    };
}
