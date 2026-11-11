import { authFetch } from '../../opscenter/api/auth.svelte';
import { latestOnly } from '../resource-push/latest-only';
import { claudeCodeRows, healthOf, type HealthReport, type HealthRow } from './plugin-health';
import type { CplugItem } from './cplugs-adapter';

export const HEALTH_ROUTE = '/cplug-owner/health';
export const SAFE_MODE_ROUTE = '/cplugs/safe-mode';

export interface PluginHealth {
    /* could not be read */
    readonly report: HealthReport | null;
    readonly claudeCode: HealthRow[];
    rowOf(plugin: Pick<CplugItem, 'cplugId' | 'publisher'>): HealthRow | undefined;
    leaveSafeMode(): Promise<void>;
    load(): Promise<void>;
}

export function createPluginHealth(fetcher: typeof authFetch = authFetch): PluginHealth {
    let report = $state<HealthReport | null>(null);
    const gate = latestOnly();
    async function load(): Promise<void> {
        const current = gate.begin();
        try {
            const next = await fetcher<HealthReport>(HEALTH_ROUTE);
            if (current()) report = next;
        } catch {
        }
    }
    return {
        get report() { return report; },
        get claudeCode() { return claudeCodeRows(report); },
        rowOf: (plugin) => healthOf(report, plugin),
        load,
        async leaveSafeMode() {
            await fetcher(SAFE_MODE_ROUTE, { method: 'PUT', body: JSON.stringify({ on: false }) });
            await load();
        },
    };
}
