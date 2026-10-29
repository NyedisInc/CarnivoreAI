import { errorText } from '../../settings-page/panel-kit/error-text';
import { resourcePush } from '../../resource-push/boot';
import { fetchKinds, fetchSettings, type Destination, type Fetcher, type Kind } from './api';

export const notify = $state<{ kinds: Kind[]; destinations: Destination[]; paused: boolean; loaded: boolean; problem: string }>({
    kinds: [], destinations: [], paused: false, loaded: false, problem: '',
});

export const FALLBACK_MS = 15000;

let fetcherInUse: Fetcher | undefined;
let inflight: Promise<void> | null = null;
let attached = 0;
let stop: (() => void) | null = null;

export function clean(dest: Destination, kind: Kind | undefined): Destination {
    const secrets: Record<string, { set: boolean }> = {};
    for (const [name, v] of Object.entries(dest.secrets ?? {})) {
        secrets[name] = { set: typeof v === 'object' && v !== null && (v as { set?: unknown }).set === true };
    }
    const config: Record<string, unknown> = {};
    for (const f of kind?.public_fields ?? []) if (dest.config?.[f.name] !== undefined) config[f.name] = dest.config[f.name];
    return { ...dest, config, secrets };
}

export function refresh(): Promise<void> {
    inflight ??= read().finally(() => { inflight = null; });
    return inflight;
}

async function read(): Promise<void> {
    try {
        if (notify.kinds.length === 0) notify.kinds = await fetchKinds(fetcherInUse);
        const settings = await fetchSettings(fetcherInUse);
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

export function attach(fetcher?: Fetcher): () => void {
    if (fetcher) fetcherInUse = fetcher;
    attached += 1;
    if (attached === 1) stop = resourcePush().pushOrPoll(() => void refresh(), FALLBACK_MS, ['notification_settings']);
    void refresh();
    return () => {
        attached -= 1;
        if (attached === 0) {
            stop?.();
            stop = null;
            fetcherInUse = undefined;
        }
    };
}
