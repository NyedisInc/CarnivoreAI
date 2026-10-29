/* the bar indicators */
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { t } from '../i18n/index.svelte';
import { toCplugItem, type CplugItem, type CplugRow } from '../plugins-page/cplugs-adapter';
import { setPages } from './page-views.svelte';
import { setPanels } from './panel-views.svelte';
import { shareRelay } from './share-relay';

const CPLUGS_TOPIC = 'cplugs';
const POLL_MS = 60_000;

export interface OverlayEntry {
    readonly key: string;
    readonly plugin: CplugItem;
    readonly view: string;
}

export const overlays = $state<{ list: OverlayEntry[] }>({ list: [] });
let following = false;

export function overlayEntries(rows: readonly CplugRow[]): OverlayEntry[] {
    const out: OverlayEntry[] = [];
    for (const row of rows) {
        if (row.runtime !== 'sidecar' || !row.enabled || row.state !== 'active') continue;
        for (const view of row.views ?? []) {
            if (view.surfaces.includes('overlay')) out.push({ key: `${row.id}:${row.install_key ?? ''}:${view.name}`, plugin: toCplugItem(row, t), view: view.name });
        }
    }
    return out;
}

async function sync(): Promise<void> {
    try {
        const body = await authFetch<{ cplugs: CplugRow[] }>('/cplugs');
        const rows = Array.isArray(body.cplugs) ? body.cplugs : [];
        overlays.list = overlayEntries(rows);
        setPanels(rows);
        shareRelay.retain(new Set(rows.flatMap((row) => (row.runtime === 'sidecar' && row.enabled && row.state === 'active' && row.install_key ? [row.install_key] : []))));
        setPages(rows);
    } catch {
    }
}

export function startOverlays(): void {
    if (following) return;
    following = true;
    const push = resourcePush();
    push.onChange((topics) => {
        if (topics.includes(CPLUGS_TOPIC)) void sync();
    });
    push.pushOrPoll(() => void sync(), POLL_MS, [CPLUGS_TOPIC]);
    void sync();
}
