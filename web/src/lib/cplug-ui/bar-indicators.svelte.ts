import { auth, authFetch } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import type { BarIndicator } from '../../cplugs/sdk';
import { t } from '../i18n/index.svelte';
import type { CplugRow } from '../plugins-page/cplugs-adapter';
import { glanceBadge, wantsBar, type GlanceBadge } from './glance';
import { watchSurface } from './surface.svelte';

const CPLUGS_TOPIC = 'cplugs';
const POLL_MS = 60_000;


const watched = $state<Record<string, { name: string; unverified: boolean; badge: GlanceBadge | null }>>({});
const watchers = new Map<string, { stop: () => void; signature: string }>();
let following = false;

function openPlugin(cplugId: string): void {
    globalThis.location.hash = `#warez/installed/plugin/${cplugId}/overview`;
}

function signatureOf(row: CplugRow): string {
    return JSON.stringify([row.install_key ?? null, row.version ?? '', row.name ?? '', row.unverified === true, row.routes ?? [], row.declared_tools ?? []]);
}

export async function syncBarIndicators(): Promise<void> {
    if (auth.state === 'signed-out') return;
    let rows: CplugRow[];
    try {
        const body = await authFetch<{ cplugs: CplugRow[] }>('/cplugs');
        rows = Array.isArray(body.cplugs) ? body.cplugs : [];
    } catch {
        return;
    }
    const live = rows.filter((r) => r.runtime === 'sidecar' && r.enabled && r.state === 'active');
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

function follow(): void {
    if (following || auth.state === 'signed-out') return;
    following = true;
    const push = resourcePush();
    push.onChange((topics) => {
        if (topics.includes(CPLUGS_TOPIC)) void syncBarIndicators();
    });
    push.pushOrPoll(() => void syncBarIndicators(), POLL_MS, [CPLUGS_TOPIC]);
    void syncBarIndicators();
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
