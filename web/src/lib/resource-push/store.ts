
export const LIVENESS = '$live';

export const FRAME_TYPE = 'resources.changed';

export type FrameBodies = Record<string, unknown>;

export type TopicListener = (topics: string[], bodies?: FrameBodies) => void;

export function familyOf(topic: string): string {
    const at = topic.indexOf(':');
    return at < 0 ? topic : topic.slice(0, at);
}

function stringsOf(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export class ResourceTopicStore {
    private advertised = new Set<string>();
    private connected = false;
    private listeners = new Set<TopicListener>();

    hello(frame: { resource_topics?: unknown }): void {
        this.connected = true;
        this.advertised = new Set(stringsOf(frame.resource_topics));
        this.emit([LIVENESS]);
    }

    closed(): void {
        const was = this.connected;
        this.connected = false;
        this.advertised.clear();
        if (was) this.emit([LIVENESS]);
    }

    frame(frame: { topics?: unknown; bodies?: unknown }): void {
        if (!this.connected) return;
        const topics = stringsOf(frame.topics);
        const bodies = frame.bodies && typeof frame.bodies === 'object' && !Array.isArray(frame.bodies) ? (frame.bodies as FrameBodies) : undefined;
        if (topics.length) this.emit(topics, bodies);
    }

    isLive(topic: string): boolean {
        return this.connected && this.advertised.has(familyOf(topic));
    }

    onChange(fn: TopicListener): () => void {
        this.listeners.add(fn);
        return () => {
            this.listeners.delete(fn);
        };
    }

    private emit(topics: string[], bodies?: FrameBodies): void {
        for (const fn of [...this.listeners]) {
            try {
                fn(topics, bodies);
            } catch {
            }
        }
    }
}

export function pushOrPoll(
    store: Pick<ResourceTopicStore, 'isLive' | 'onChange'>,
    refresh: () => void,
    intervalMs: number,
    topics: readonly string[],
): () => void {
    let timer: ReturnType<typeof setInterval> | null = null;
    const live = (): boolean => topics.every((t) => store.isLive(t));
    const arm = (): void => {
        if (live()) {
            if (timer !== null) clearInterval(timer);
            timer = null;
        } else if (timer === null) {
            timer = setInterval(refresh, intervalMs);
        }
    };
    const off = store.onChange((moved) => {
        arm();
        if (live() && (moved.includes(LIVENESS) || moved.some((t) => topics.includes(t)))) refresh();
    });
    arm();
    return () => {
        off();
        if (timer !== null) clearInterval(timer);
        timer = null;
    };
}
