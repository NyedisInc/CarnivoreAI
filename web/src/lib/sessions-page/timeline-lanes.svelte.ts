import { authFetch } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { LIVENESS } from '../resource-push/store';
import { SESSION_TIMELINE_TOPIC } from '../../opscenter/api/session-timeline.svelte';
import type { SessionTimeline } from '../../opscenter/cells/timeline/types';

export const MAX_IN_FLIGHT = 4;

const FALLBACK_POLL_MS = 30000;

export interface TimelineReaders {
    timeline(sessionUuid: string): Promise<SessionTimeline>;
}

export interface TimelinePush {
    onChange(fn: (topics: string[]) => void): () => void;
    isLive(topic: string): boolean;
}

export const defaultTimelineReaders: TimelineReaders = {
    timeline: (uuid) => authFetch<SessionTimeline>(`/sessions/${encodeURIComponent(uuid)}/timeline`),
};

export interface LaneRead {
    readonly status: 'idle' | 'loading' | 'ready' | 'error';
    readonly tl: SessionTimeline | null;
}

export class TimelineLanes {
    lanes = $state.raw<Readonly<Record<string, LaneRead>>>({});

    readonly #readers: TimelineReaders;
    readonly #push: TimelinePush | null;
    readonly #uuidOfRow = new Map<number, string>();
    readonly #onScreen = new Set<string>();
    readonly #queue: string[] = [];
    readonly #inFlight = new Set<string>();
    readonly #dirty = new Set<string>();
    readonly #stale = new Set<string>();
    #off: (() => void) | null = null;
    #timer: ReturnType<typeof setInterval> | null = null;
    #generation = 0;

    constructor(readers: TimelineReaders = defaultTimelineReaders, push: TimelinePush | null = null) {
        this.#readers = readers;
        this.#push = push;
    }

    start(): void {
        this.stop();
        const push = this.#push ?? resourcePush();
        const arm = (): void => {
            if (push.isLive(SESSION_TIMELINE_TOPIC)) {
                if (this.#timer !== null) clearInterval(this.#timer);
                this.#timer = null;
            } else if (this.#timer === null) {
                this.#timer = setInterval(() => this.#changed(null), FALLBACK_POLL_MS);
            }
        };
        this.#off = push.onChange((topics) => {
            arm();
            if (topics.includes(LIVENESS)) {
                if (push.isLive(SESSION_TIMELINE_TOPIC)) this.#changed(null);
                return;
            }
            for (const topic of topics) {
                if (topic === SESSION_TIMELINE_TOPIC) this.#changed(null);
                else if (topic.startsWith('bookmarks:') || topic.startsWith(`${SESSION_TIMELINE_TOPIC}:`)) {
                    const uuid = this.#uuidOfRow.get(Number(topic.slice(topic.indexOf(':') + 1)));
                    if (uuid) this.#changed(uuid);
                }
            }
        });
        arm();
    }

    stop(): void {
        this.#generation += 1;
        this.#off?.();
        this.#off = null;
        if (this.#timer !== null) clearInterval(this.#timer);
        this.#timer = null;
        this.#queue.length = 0;
    }

    know(uuid: string, rowId: number | null): void {
        if (rowId !== null) this.#uuidOfRow.set(rowId, uuid);
    }

    show(uuid: string, on: boolean): void {
        if (!on) {
            this.#onScreen.delete(uuid);
            return;
        }
        this.#onScreen.add(uuid);
        if (!(uuid in this.lanes) || this.#stale.has(uuid)) this.#want(uuid);
    }

    #changed(uuid: string | null): void {
        for (const u of uuid ? [uuid] : Object.keys(this.lanes)) {
            if (this.#onScreen.has(u)) this.#want(u);
            else this.#stale.add(u);
        }
    }

    /* already running */
    #want(uuid: string): void {
        this.#stale.delete(uuid);
        if (this.#inFlight.has(uuid)) this.#dirty.add(uuid);
        else if (!this.#queue.includes(uuid)) {
            this.#queue.push(uuid);
            if (!(uuid in this.lanes)) this.#set(uuid, { status: 'idle', tl: null });
        }
        this.#pump();
    }

    #pump(): void {
        while (this.#inFlight.size < MAX_IN_FLIGHT && this.#queue.length) {
            const uuid = this.#queue.shift() as string;
            if (!this.#onScreen.has(uuid)) {
                this.#stale.add(uuid);
                continue;
            }
            this.#inFlight.add(uuid);
            void this.#read(uuid);
        }
    }

    async #read(uuid: string): Promise<void> {
        const generation = this.#generation;
        const before = this.lanes[uuid]?.tl ?? null;
        this.#set(uuid, { status: 'loading', tl: before });
        try {
            const tl = await this.#readers.timeline(uuid);
            if (generation === this.#generation) this.#set(uuid, { status: 'ready', tl });
        } catch {
            if (generation === this.#generation) this.#set(uuid, { status: 'error', tl: before });
        } finally {
            this.#inFlight.delete(uuid);
            if (generation === this.#generation) {
                if (this.#dirty.delete(uuid)) this.#want(uuid);
                else this.#pump();
            }
        }
    }

    #set(uuid: string, read: LaneRead): void {
        this.lanes = { ...this.lanes, [uuid]: read };
    }
}
