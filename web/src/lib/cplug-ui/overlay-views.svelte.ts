import { t } from '../i18n/index.svelte';
import { toCplugItem, type CplugItem, type CplugRow } from '../plugins-page/cplugs-adapter';
import { pluginsStore } from '../plugins/store.svelte';
import { setPages } from './page-views.svelte';
import { setPanels } from './panel-views.svelte';
import { shareRelay } from './share-relay';

export interface OverlayEntry {
    readonly key: string;
    readonly plugin: CplugItem;
    readonly view: string;
}

export const overlays = $state<{ list: OverlayEntry[] }>({ list: [] });
let following = false;
let stopRows: (() => void) | null = null;
let stopAcquire: (() => void) | null = null;

export function overlayEntries(rows: readonly CplugRow[]): OverlayEntry[] {
    const out: OverlayEntry[] = [];
    for (const row of rows) {
        const isSidecar = row.runtime === 'sidecar';
        const hasCompiledViews = row.runtime === 'compiled' && (row.views?.length ?? 0) > 0;
        if ((!isSidecar && !hasCompiledViews) || !row.enabled || row.state !== 'active') continue;
        for (const view of row.views ?? []) {
            if (view.surfaces.includes('overlay')) out.push({ key: `${row.id}:${row.install_key ?? ''}:${view.name}`, plugin: toCplugItem(row, t), view: view.name });
        }
    }
    return out;
}

function applyRows(rows: readonly CplugRow[]): void {
    overlays.list = overlayEntries(rows);
    setPanels(rows);
    shareRelay.retain(new Set(rows.flatMap((row) => (row.runtime === 'sidecar' && row.enabled && row.state === 'active' && row.install_key ? [row.install_key] : []))));
    setPages(rows);
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
        overlays.list = [];
    });
}

export function startOverlays(): void {
    ensureResetHook();
    if (following) return;
    following = true;
    stopRows = pluginsStore.onRows(applyRows);
    stopAcquire = pluginsStore.acquire();
    if (pluginsStore.read) applyRows(pluginsStore.rows);
}
