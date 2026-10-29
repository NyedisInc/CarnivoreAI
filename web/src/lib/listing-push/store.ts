
export interface CollectionState {
    rows: Record<string, unknown>[];
    ok: boolean;
    status: number | null;
    detail: unknown;
    meta: Record<string, unknown>;
}

export interface CollectionChange {
    upsert?: Array<{
        key: string;
        fields?: Record<string, unknown>;
        nested?: Record<string, Record<string, unknown>>;
        drop?: string[];
    }>;
    remove?: string[];
    order?: string[];
    status?: { ok: boolean; status: number | null; detail: unknown; meta: Record<string, unknown> };
}

export interface DeltaFrame {
    type: 'listing.delta';
    stream: string;
    seq: number;
    changes: Record<string, CollectionChange>;
}

export interface Snapshot {
    stream: string;
    seq: number;
    collections: Record<string, CollectionState>;
}

export const LIVENESS = '$live';

export const PROVISIONAL_FIELDS: Readonly<Record<string, unknown>> = {
    provisional: true,
    activity_status: 'unknown',
    status_source: 'none',
    startup_gate: null,
    unread: null,
};

export const PROVISIONAL_WINDOW_MS = 4000;

const KEY_OF: Record<string, (row: Record<string, unknown>) => string | null> = {
    list: (row) => {
        const session = row.session as { id?: unknown } | null | undefined;
        return session && typeof session.id === 'string' ? session.id : null;
    },
    attachable: (row) => (typeof row.name === 'string' ? row.name : null),
};

function keyOf(name: string, row: Record<string, unknown>): string | null {
    const fn = KEY_OF[name];
    if (fn) return fn(row);
    return typeof row.session_uuid === 'string' ? row.session_uuid : null;
}

function clone<T>(value: T): T {
    return JSON.parse(JSON.stringify(value)) as T;
}

export interface StoreDeps {
    fetchSnapshot(): Promise<Snapshot>;
    setTimer?(fn: () => void, ms: number): unknown;
    clearTimer?(handle: unknown): void;
    random?(): number;
}

export type ChangeListener = (names: string[]) => void;

export const RESYNC_RETRY_MS = 5000;

export const RESYNC_RETRY_MAX_MS = 60000;

export const RESYNC_JITTER_MS = 4000;
export class ListingStore {
    private stream: string | null = null;
    private seq = 0;
    private live = false;
    private syncing: Promise<void> | null = null;
    private buffered: DeltaFrame[] = [];
    private collections = new Map<string, { byKey: Map<string, Record<string, unknown>>; order: string[]; status: Omit<CollectionState, 'rows'> }>();
    private listeners = new Set<ChangeListener>();
    private retry: unknown = null;
    private retryFailures = 0;
    private jitterTimer: unknown = null;
    private jitterRun: Promise<void> | null = null;
    private hasSynced = false;
    private cached: Snapshot | null = null;
    private cachedUntil = 0;

    constructor(private readonly deps: StoreDeps) {}

    isLive(): boolean {
        return this.live;
    }

    rows<T = Record<string, unknown>>(name: string): T[] | null {
        if (!this.live) return null;
        const held = this.collections.get(name);
        if (!held || !held.status.ok) return null;
        return clone(held.order.map((key) => held.byKey.get(key)).filter(Boolean)) as T[];
    }

    snapshot(): Snapshot | null {
        if (!this.live || this.stream === null) return null;
        const collections: Record<string, CollectionState> = {};
        for (const [name, held] of this.collections) {
            if (!held.status.ok) continue;
            collections[name] = {
                rows: clone(held.order.map((key) => held.byKey.get(key)).filter(Boolean)) as Record<string, unknown>[],
                ...clone(held.status),
            };
        }
        return { stream: this.stream, seq: this.seq, collections };
    }

    hydrate(snap: Snapshot | null): void {
        if (this.hasSynced || !snap || typeof snap !== 'object' || !snap.collections) return;
        this.cached = snap;
        this.cachedUntil = Date.now() + PROVISIONAL_WINDOW_MS;
    }

    provisionalRows<T = Record<string, unknown>>(name: string): T[] | null {
        if (this.live || this.hasSynced || !this.cached || Date.now() > this.cachedUntil) return null;
        const col = this.cached.collections[name];
        if (!col || col.ok === false || !Array.isArray(col.rows)) return null;
        return clone(col.rows).map((row) => (
            name === 'list' ? { ...row, ...PROVISIONAL_FIELDS } : { ...row, provisional: true }
        )) as T[];
    }

    meta(name: string): Record<string, unknown> | null {
        if (!this.live) return null;
        const held = this.collections.get(name);
        return held && held.status.ok ? clone(held.status.meta || {}) : null;
    }

    onChange(fn: ChangeListener): () => void {
        this.listeners.add(fn);
        return () => this.listeners.delete(fn);
    }

    hello(): Promise<void> {
        return this.hasSynced ? this.resyncJittered() : this.resync();
    }

    closed(): void {
        this.cancelJitter();
        this.syncing = null;
        this.buffered = [];
        this.setLive(false);
    }

    frame(frame: DeltaFrame): void {
        if (!frame || typeof frame.seq !== 'number' || !frame.changes) return;
        if (this.syncing) {
            this.buffered.push(frame);
            return;
        }
        if (!this.live) return;
        if (frame.stream !== this.stream) {
            void this.resyncJittered();
            return;
        }
        if (frame.seq > this.seq + 1) {
            void this.resync();
            return;
        }
        if (frame.seq <= this.seq) return;
        this.apply(frame);
        this.notify(Object.keys(frame.changes));
    }

    resync(): Promise<void> {
        if (this.syncing) return this.syncing;
        this.buffered = [];
        let run: Promise<void> | null = null;
        run = (async () => {
            let snap: Snapshot;
            try {
                snap = await this.deps.fetchSnapshot();
            } catch (err) {
                console.warn('ListingPush: snapshot unavailable, readers poll their routes:', (err as Error)?.message);
                if (this.syncing === run) this.syncing = null;
                this.setLive(false);
                this.scheduleRetry();
                return;
            }
            if (this.syncing !== run) return;
            this.load(snap);
            this.hasSynced = true;
            this.cached = null;
            this.retryFailures = 0;
            const pending = this.buffered.filter((f) => f.stream === snap.stream && f.seq > snap.seq)
                .sort((a, b) => a.seq - b.seq);
            this.buffered = [];
            this.syncing = null;
            for (const f of pending) {
                if (f.seq !== this.seq + 1) {
                    void this.resync();
                    return;
                }
                this.apply(f);
            }
            this.live = true;
            this.notify([LIVENESS, ...this.collections.keys()]);
        })();
        this.syncing = run;
        return run;
    }

    private resyncJittered(): Promise<void> {
        if (this.jitterRun) return this.jitterRun;
        const set = this.deps.setTimer ?? ((fn: () => void, ms: number) => setTimeout(fn, ms));
        const run: Promise<void> = new Promise<void>((resolve) => {
            this.jitterTimer = set(() => {
                this.jitterTimer = null;
                this.jitterRun = null;
                void this.resync().then(resolve);
            }, this.spread(RESYNC_JITTER_MS));
        });
        this.jitterRun = run;
        return run;
    }

    private cancelJitter(): void {
        if (this.jitterTimer === null) return;
        const clear = this.deps.clearTimer ?? ((h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>));
        clear(this.jitterTimer);
        this.jitterTimer = null;
        this.jitterRun = null;
    }

    private spread(max: number): number {
        return Math.floor((this.deps.random ?? Math.random)() * max);
    }

    private scheduleRetry(): void {
        const set = this.deps.setTimer ?? ((fn: () => void, ms: number) => setTimeout(fn, ms));
        if (this.retry !== null) return;
        const ceiling = Math.min(RESYNC_RETRY_MS * 2 ** this.retryFailures, RESYNC_RETRY_MAX_MS);
        this.retryFailures += 1;
        this.retry = set(() => {
            this.retry = null;
            if (!this.live && !this.syncing) void this.resync();
        }, Math.floor(ceiling / 2) + this.spread(Math.ceil(ceiling / 2)));
    }

    private load(snap: Snapshot): void {
        this.stream = snap.stream;
        this.seq = snap.seq;
        this.collections.clear();
        for (const [name, col] of Object.entries(snap.collections || {})) {
            const byKey = new Map<string, Record<string, unknown>>();
            const order: string[] = [];
            for (const row of col.rows || []) {
                const key = keyOf(name, row);
                if (key === null || byKey.has(key)) continue;
                byKey.set(key, row);
                order.push(key);
            }
            this.collections.set(name, {
                byKey, order,
                status: { ok: col.ok !== false, status: col.status ?? null, detail: col.detail ?? null, meta: col.meta || {} },
            });
        }
    }

    private apply(frame: DeltaFrame): void {
        for (const [name, change] of Object.entries(frame.changes)) {
            let held = this.collections.get(name);
            if (!held) {
                held = { byKey: new Map(), order: [], status: { ok: true, status: null, detail: null, meta: {} } };
                this.collections.set(name, held);
            }
            for (const up of change.upsert || []) {
                const row = held.byKey.get(up.key) ?? {};
                if (!held.byKey.has(up.key)) {
                    held.byKey.set(up.key, row);
                    held.order.push(up.key);
                }
                Object.assign(row, up.fields || {});
                for (const [field, part] of Object.entries(up.nested || {})) {
                    const inner = row[field];
                    row[field] = { ...(inner && typeof inner === 'object' ? inner as Record<string, unknown> : {}), ...part };
                }
                for (const field of up.drop || []) delete row[field];
            }
            for (const key of change.remove || []) held.byKey.delete(key);
            held.order = (change.order || held.order).filter((key) => held!.byKey.has(key));
            if (change.status) {
                held.status = { ok: change.status.ok !== false, status: change.status.status ?? null,
                    detail: change.status.detail ?? null, meta: change.status.meta || {} };
            }
        }
        this.seq = frame.seq;
    }

    private setLive(on: boolean): void {
        if (this.live === on) return;
        this.live = on;
        this.notify([LIVENESS]);
    }

    private notify(names: string[]): void {
        for (const fn of [...this.listeners]) {
            try {
                fn(names);
            } catch (err) {
                console.warn('ListingPush: a listener threw and was skipped', err);
            }
        }
    }
}

export function pushOrPoll(
    store: Pick<ListingStore, 'isLive' | 'onChange'>,
    refresh: () => void,
    intervalMs: number,
    collections: readonly string[],
): () => void {
    let timer: ReturnType<typeof setInterval> | null = null;
    const arm = (): void => {
        if (store.isLive()) {
            if (timer !== null) clearInterval(timer);
            timer = null;
        } else if (timer === null) {
            timer = setInterval(refresh, intervalMs);
        }
    };
    const off = store.onChange((names) => {
        arm();
        if (store.isLive() && (names.includes(LIVENESS) || names.some((n) => collections.includes(n)))) refresh();
    });
    arm();
    return () => {
        off();
        if (timer !== null) clearInterval(timer);
        timer = null;
    };
}
