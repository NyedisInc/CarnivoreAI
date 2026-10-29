import { FRAME_TYPE, ResourceTopicStore, pushOrPoll } from './store';

interface HostEvents {
    subscribe(handler: (frame: { type?: string }) => void): () => void;
    isConnected(): boolean;
    lastHello?(): { resource_topics?: unknown } | null;
}

export interface ResourcePushGlobal {
    store: ResourceTopicStore;
    isLive(topic: string): boolean;
    onChange(fn: (topics: string[]) => void): () => void;
    pushOrPoll(refresh: () => void, intervalMs: number, topics: readonly string[]): () => void;
}

let booted: ResourcePushGlobal | null = null;

function page(): Record<string, unknown> {
    return globalThis as unknown as Record<string, unknown>;
}

export function bootResourcePush(): ResourcePushGlobal {
    if (booted) return booted;
    const store = new ResourceTopicStore();
    const surface: ResourcePushGlobal = {
        store,
        isLive: (topic) => store.isLive(topic),
        onChange: (fn) => store.onChange(fn),
        pushOrPoll: (refresh, ms, topics) => pushOrPoll(store, refresh, ms, topics),
    };
    page().ResourcePush = surface;
    booted = surface;
    const events = page().AppEvents as HostEvents | undefined;
    if (events && typeof events.subscribe === 'function') {
        events.subscribe((frame) => {
            if (!frame || typeof frame.type !== 'string') return;
            if (frame.type === 'events.hello') store.hello(frame as { resource_topics?: unknown });
            else if (frame.type === 'events.closed') store.closed();
            else if (frame.type === FRAME_TYPE) store.frame(frame as { topics?: unknown });
        });
        const hello = events.isConnected() && typeof events.lastHello === 'function' ? events.lastHello() : null;
        if (hello) store.hello(hello);
    }
    return surface;
}

export function resourcePush(): ResourcePushGlobal {
    return booted ?? bootResourcePush();
}
