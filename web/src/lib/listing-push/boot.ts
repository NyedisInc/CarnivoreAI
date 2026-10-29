import { ListingStore, pushOrPoll, type DeltaFrame, type Snapshot } from './store';
import { hydrateAndPersist } from './cache';

interface HostEvents {
    subscribe(handler: (frame: { type?: string }) => void): () => void;
    isConnected(): boolean;
}

interface HostApi {
    call(endpoint: string): Promise<unknown>;
}

export interface ListingPushGlobal {
    store: ListingStore;
    isLive(): boolean;
    rows<T = Record<string, unknown>>(name: string): T[] | null;
    meta(name: string): Record<string, unknown> | null;
    onChange(fn: (names: string[]) => void): () => void;
    pushOrPoll(refresh: () => void, intervalMs: number, collections: readonly string[]): () => void;
    provisionalRows<T = Record<string, unknown>>(name: string): Promise<T[] | null>;
}

let booted: ListingPushGlobal | null = null;

const waiting: Array<() => void> = [];

export function whenListingPushBooted(fn: () => void): void {
    if (booted) fn();
    else waiting.push(fn);
}

function page(): Record<string, unknown> {
    return globalThis as unknown as Record<string, unknown>;
}

export function bootListingPush(): ListingPushGlobal {
    if (booted) return booted;
    const store = new ListingStore({
        fetchSnapshot: async () => {
            const api = page().API as HostApi | undefined;
            if (!api || typeof api.call !== 'function') throw new Error('API client not loaded');
            return (await api.call('/sessions/listing')) as Snapshot;
        },
    });
    const hydrated = hydrateAndPersist(store);
    const surface: ListingPushGlobal = {
        store,
        isLive: () => store.isLive(),
        rows: (name) => store.rows(name),
        meta: (name) => store.meta(name),
        onChange: (fn) => store.onChange(fn),
        pushOrPoll: (refresh, ms, names) => pushOrPoll(store, refresh, ms, names),
        provisionalRows: async <T>(name: string) => {
            await hydrated;
            return store.provisionalRows<T>(name);
        },
    };
    page().ListingPush = surface;
    booted = surface;
    for (const fn of waiting.splice(0)) fn();
    attach(store);
    const led = page().SessionHeaderLed as { stop?(): void; start?(): void } | undefined;
    if (led && typeof led.stop === 'function' && typeof led.start === 'function') {
        led.stop();
        led.start();
    }
    return surface;
}

function attach(store: ListingStore): void {
    const events = page().AppEvents as HostEvents | undefined;
    if (!events || typeof events.subscribe !== 'function') return;
    events.subscribe((frame) => {
        if (!frame || typeof frame.type !== 'string') return;
        if (frame.type === 'events.hello') void store.hello();
        else if (frame.type === 'events.closed') store.closed();
        else if (frame.type === 'listing.delta') store.frame(frame as unknown as DeltaFrame);
    });
    if (events.isConnected()) void store.hello();
}
