import { mergeLiveRow, type DrawerRow } from '../drawer/fetch';
import { whenListingPushBooted } from '../listing-push/boot';
import type { SessionListItem } from '../sessions/types';
import type { HistoryApi } from './history-api';

export interface LiveSession {
    readonly row: DrawerRow;
    readonly info: SessionListItem;
}

type PushSource = { onChange?(fn: (names: string[]) => void): () => void };

export class LiveRows {
    byId = $state<ReadonlyMap<string, LiveSession>>(new Map());

    readonly #api: HistoryApi;
    #ticket = 0;
    #off: (() => void) | null = null;
    #stopped = false;

    constructor(api: HistoryApi) {
        this.#api = api;
    }

    of(liveSessionId: string | null | undefined): LiveSession | undefined {
        return liveSessionId ? this.byId.get(liveSessionId) : undefined;
    }

    async refresh(): Promise<void> {
        const read = this.#api.liveListing;
        if (!read) return;
        const mine = ++this.#ticket;
        let items: readonly unknown[] | null;
        try {
            items = await read.call(this.#api);
        } catch (error) {
            console.warn('CloudeOpscenter: live listing unavailable for the sessions page', error);
            return;
        }
        if (mine !== this.#ticket || !items) return;
        const next = new Map<string, LiveSession>();
        for (const raw of items) {
            const info = raw as SessionListItem;
            const id = info.session?.id;
            if (!id) continue;
            const rows: DrawerRow[] = [];
            mergeLiveRow(rows, info as Parameters<typeof mergeLiveRow>[1]);
            if (rows[0]) next.set(id, { row: rows[0], info });
        }
        this.byId = next;
    }

    start(): void {
        this.#stopped = false;
        void this.refresh();
        whenListingPushBooted(() => {
            if (this.#stopped || this.#off) return;
            const push = (globalThis as { ListingPush?: PushSource }).ListingPush;
            this.#off = push?.onChange?.((names) => {
                if (names.includes('list')) void this.refresh();
            }) ?? null;
        });
    }

    stop(): void {
        this.#stopped = true;
        this.#off?.();
        this.#off = null;
        this.#ticket++;
    }
}
