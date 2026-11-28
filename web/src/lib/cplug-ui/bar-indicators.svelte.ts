import { auth } from '../../opscenter/api/auth.svelte';
import type { BarIndicator } from '../../plugins/sdk';
import { t } from '../i18n/index.svelte';
import type { CplugRow } from '../plugins-page/cplugs-adapter';
import { pluginsStore } from '../plugins/store.svelte';
import { canDrawGlance, glanceBadge, wantsBar, type GlanceBadge } from './glance';
import { watchSurface } from './surface.svelte';

const watched = $state<Record<string, { name: string; unverified: boolean; badge: GlanceBadge | null }>>({});
const watchers = new Map<string, { stop: () => void; signature: string }>();
let following = false;
let stopRows: (() => void) | null = null;
let stopAcquire: (() => void) | null = null;

function openPlugin(cplugId: string): void {
    globalThis.location.hash = `#warez/installed/plugin/${cplugId}/overview`;
}

function signatureOf(row: CplugRow): string {
    return JSON.stringify([row.install_key ?? null, row.version ?? '', row.name ?? '', row.unverified === true, row.routes ?? [], row.declared_tools ?? []]);
}

function applyBarRows(rows: readonly CplugRow[]): void {
    const live = rows.filter((r) => r.runtime === 'sidecar' && r.enabled && r.state === 'active' && canDrawGlance(r.unrendered_surfaces));
    for (const id of [...watchers.keys()]) {
        if (!live.some((r) => r.id === id)) {
            watchers.get(id)?.stop();
            watchers.delete(id);
            delete watched[id];
        }
    }
    for (const row of live) {
        const signature = signatureOf(row);
        const running = watchers.get(row.id);
        if (running?.signature === signature) continue;
        running?.stop();
        const declared = { routes: row.routes ?? [], tools: row.declared_tools ?? [] };
        watched[row.id] = { name: row.name || row.id, unverified: row.unverified === true, badge: null };
        const stop = watchSurface({ cplugId: row.id, installKey: row.install_key ?? null, surface: 'glance' }, (state) => {
            const badge = state.kind === 'ready' ? glanceBadge(state.document, declared) : null;
            if (watched[row.id]) watched[row.id]!.badge = badge;
        });
        watchers.set(row.id, { stop, signature });
    }
}

let resetWired = false;
function ensureResetHook(): void {
    if (resetWired) return;
    resetWired = true;
    pluginsStore.onReset(() => {
        following = false;
        stopRows?.();
        stopRows = null;
        stopAcquire?.();
        stopAcquire = null;
        for (const watcher of watchers.values()) watcher.stop();
        watchers.clear();
        for (const id of Object.keys(watched)) delete watched[id];
    });
}

export async function syncBarIndicators(): Promise<void> {
    if (auth.state === 'signed-out') return;
    ensureResetHook();
    const ok = await pluginsStore.refresh({ force: true });
    if (ok) applyBarRows(pluginsStore.rows);
}

function follow(): void {
    if (following || auth.state === 'signed-out') return;
    ensureResetHook();
    following = true;
    stopRows = pluginsStore.onRows(applyBarRows);
    stopAcquire = pluginsStore.acquire();
    if (pluginsStore.read) applyBarRows(pluginsStore.rows);
}

export function thirdPartyBarIndicators(): (BarIndicator & { cplugId: string })[] {
    follow();
    return Object.keys(watched).sort().map((id) => {
        const entry = watched[id]!;
        return {
            cplugId: id,
            id: 'glance',
            icon: 'plug',
            visible: () => entry.badge !== null && wantsBar(entry.badge),
            label: () => t('cplug_ui.bar.label', { mark: t(entry.unverified ? 'cplug_ui.mark.unverified' : 'cplug_ui.mark.third_party'), name: entry.name, text: entry.badge?.status ? t(`cplug_ui.status.${entry.badge.status}`) : (entry.badge?.text ?? '') }),
            tone: () => (entry.badge?.tone === 'danger' || entry.badge?.tone === 'warn' || entry.badge?.status === 'dead' ? 'lit' : 'quiet'),
            run: () => openPlugin(id),
        };
    });
}
