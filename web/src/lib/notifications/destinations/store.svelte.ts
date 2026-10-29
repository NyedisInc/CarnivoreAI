import { errorText } from '../../settings-page/panel-kit/error-text';
import { createPushedStore } from '../../resource-push/pushed-store';
import { fetchKinds, fetchSettings, type Destination, type Fetcher, type Kind } from './api';

export const notify = $state<{ kinds: Kind[]; destinations: Destination[]; paused: boolean; loaded: boolean; problem: string }>({
    kinds: [], destinations: [], paused: false, loaded: false, problem: '',
});

export const FALLBACK_MS = 15000;

export function clean(dest: Destination, kind: Kind | undefined): Destination {
    const secrets: Record<string, { set: boolean }> = {};
    for (const [name, v] of Object.entries(dest.secrets ?? {})) {
        secrets[name] = { set: typeof v === 'object' && v !== null && (v as { set?: unknown }).set === true };
    }
    const config: Record<string, unknown> = {};
    for (const f of kind?.public_fields ?? []) if (dest.config?.[f.name] !== undefined) config[f.name] = dest.config[f.name];
    return { ...dest, config, secrets };
}

async function read(fetcher: Fetcher | undefined): Promise<void> {
    try {
        if (notify.kinds.length === 0) notify.kinds = await fetchKinds(fetcher);
        const settings = await fetchSettings(fetcher);
        notify.destinations = settings.destinations.map((d) => clean(d, notify.kinds.find((k) => k.id === d.kind)));
        notify.paused = settings.paused;
        notify.problem = '';
        notify.loaded = true;
    } catch (error) {
        notify.problem = errorText(error);
    }
}

export function upsert(dest: Destination): void {
    const next = clean(dest, notify.kinds.find((k) => k.id === dest.kind));
    const at = notify.destinations.findIndex((d) => d.id === next.id);
    if (at < 0) notify.destinations = [...notify.destinations, next];
    else notify.destinations = notify.destinations.map((d, i) => (i === at ? next : d));
}

export const { refresh, attach } = createPushedStore<Fetcher>({ topics: ['notification_settings'], pollMs: FALLBACK_MS, read });
