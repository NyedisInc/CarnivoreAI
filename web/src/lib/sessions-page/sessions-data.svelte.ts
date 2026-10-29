import { authFetch } from '../../opscenter/api/auth.svelte';
import { subscribe } from '../../opscenter/api/events.svelte';
import { resourcePush } from '../resource-push/boot';
import { whenListingPushBooted } from '../listing-push/boot';
import type { HistoryApi, HistoryGroup, HistoryPage, HistoryProject } from '../projects-shared/history-api';
import { MAX_PAGES } from '../projects-shared/history-query';
import { LiveRows } from '../projects-shared/live-rows.svelte';
import type { SessionListItem } from '../sessions/types';
import { isAgentRow, rowsFromGroups, type PageRow, type Signals } from './filters';
import { closedRowsFrom } from './closed-model';
import { isAutomatedOnly } from '../projects-shared/ledger-model';

const POLL_MS = 15000;

const GROUPS_PER_PAGE = 100;
const SESSIONS_PER_GROUP = 500;

/*  hidden  */
export function agentQuery(offset = 0, showHidden = false): string {
    const q = new URLSearchParams({
        state: 'running,asleep',
        agent: 'claude,codex',
        include_empty: 'true',
        project_state: 'all',
        include_automated: showHidden ? 'true' : 'false',
        sort: 'recent',
        limit: String(GROUPS_PER_PAGE),
        session_limit: String(SESSIONS_PER_GROUP),
    });
    if (offset) q.set('offset', String(offset));
    return q.toString();
}

export function closedQuery(offset = 0, showHidden = false, archived = false): string {
    const q = new URLSearchParams({
        state: showHidden || archived ? 'closed,removed,unknown' : 'closed,unknown',
        agent: 'claude,codex',
        include_empty: 'false',
        project_state: 'all',
        include_automated: showHidden ? 'true' : 'false',
        sort: 'recent',
        limit: String(GROUPS_PER_PAGE),
        session_limit: String(SESSIONS_PER_GROUP),
    });
    if (offset) q.set('offset', String(offset));
    return q.toString();
}

export interface SessionsReaders {
    records(): Promise<readonly unknown[] | null>;
    counts(): Promise<Readonly<Record<string, number>>>;
    usage?(): Promise<Readonly<Record<string, number>> | null>;
    latest?(): Promise<Readonly<Record<string, LatestLine>>>;
}

export interface LatestLine {
    readonly text: string;
    readonly at?: string | null;
    readonly kind: string;
}

export const defaultReaders: SessionsReaders = {
    records: async () => {
        const pushed = (globalThis as { ListingPush?: { rows?(name: string): unknown[] | null } }).ListingPush?.rows?.('records');
        return pushed ?? authFetch<unknown[]>('/sessions/records');
    },
    counts: async () => (await authFetch<{ by_session?: Record<string, number> }>('/session-conversations/counts')).by_session ?? {},
    usage: async () => {
        const answer = await authFetch<{ state?: string; by_session?: Record<string, { worked_s?: number }> }>('/sessions/usage?days=30');
        if (answer.state !== 'ok') return null;
        return Object.fromEntries(Object.entries(answer.by_session ?? {}).map(([uuid, u]) => [uuid, u.worked_s ?? 0]));
    },
    latest: async () => (await authFetch<{ by_session?: Record<string, LatestLine> }>('/sessions/latest-lines')).by_session ?? {},
};

interface RecordRow {
    session_uuid?: string;
    asleep?: boolean;
    unread?: boolean;
}

export class SessionsData implements Signals {
    rows = $state<readonly PageRow[]>([]);
    emptyProjects = $state<readonly HistoryProject[]>([]);
    archivedProjects = $state<readonly HistoryProject[]>([]);
    closedRows = $state<readonly PageRow[]>([]);
    automatedProjectIds = $state<ReadonlySet<number>>(new Set());
    showHidden = $state(false);
    showArchived = false;
    status = $state<'loading' | 'ready' | 'error'>('loading');
    errorText = $state('');
    /* did not answer */
    peerUnavailable = $state<readonly string[]>([]);
    asleepUnreadSet = $state<ReadonlySet<string>>(new Set());
    conversations = $state<Readonly<Record<string, number>>>({});
    usage = $state<Readonly<Record<string, number>> | null>(null);
    latest = $state<Readonly<Record<string, LatestLine>>>({});
    pinTick = $state(0);
    /* could not be read */
    listingDown = $state(false);
    readonly liveRows: LiveRows;

    readonly #api: HistoryApi;
    readonly #readers: SessionsReaders;
    readonly #noProject: string;
    readonly #noDatastore: string;
    #ticket = 0;
    #stops: Array<() => void> = [];

    constructor(api: HistoryApi, readers: SessionsReaders, noProject: string, noDatastore: string) {
        this.#api = api;
        this.#readers = readers;
        this.#noProject = noProject;
        this.#noDatastore = noDatastore;
        const read = api.liveListing;
        const watched: HistoryApi = read
            ? {
                  ...api,
                  liveListing: async () => {
                      try {
                          const items = await read.call(api);
                          this.listingDown = false;
                          return items;
                      } catch (error) {
                          this.listingDown = true;
                          throw error;
                      }
                  },
              }
            : api;
        this.liveRows = new LiveRows(watched);
    }

    live(s: { live_session_id: string | null }): SessionListItem | undefined {
        return this.liveRows.of(s.live_session_id)?.info;
    }

    asleepUnread(sessionUuid: string): boolean {
        return this.asleepUnreadSet.has(sessionUuid);
    }

    start(): void {
        this.stop();
        void this.refresh();
        this.liveRows.start();
        this.#stops.push(
            resourcePush().pushOrPoll(() => void this.refresh(), POLL_MS, ['projects']),
            subscribe('sessions.changed', () => void this.refresh()),
            subscribe('preferences.changed', () => void Promise.resolve().then(() => (this.pinTick += 1))),
        );
        whenListingPushBooted(() => {
            const push = (globalThis as { ListingPush?: { onChange?(fn: (names: string[]) => void): () => void } }).ListingPush;
            const off = push?.onChange?.((names) => {
                if (names.includes('records')) void this.readUnread();
            });
            if (off) this.#stops.push(off);
        });
    }

    setShowHidden(on: boolean): void {
        if (on === this.showHidden) return;
        this.showHidden = on;
        void this.refresh();
    }

    setShowArchived(on: boolean): void {
        if (on === this.showArchived) return;
        this.showArchived = on;
        if (!this.showHidden) void this.readClosed();
    }

    stop(): void {
        this.#ticket += 1;
        this.liveRows.stop();
        for (const off of this.#stops.splice(0)) off();
    }

    async refresh(): Promise<void> {
        const mine = ++this.#ticket;
        try {
            const { groups, peers, unavailable } = await this.#walk((offset) => agentQuery(offset, this.showHidden));
            if (mine !== this.#ticket) return;
            const live = groups.filter((g) => !g.project?.archived_at);
            this.rows = rowsFromGroups(live, peers.filter((g) => !g.project?.archived_at), this.#noProject);
            this.emptyProjects = live.flatMap((g) => (g.project && !g.sessions.some(isAgentRow) ? [g.project] : []));
            this.archivedProjects = groups.flatMap((g) => (g.project?.archived_at ? [g.project] : []));
            this.automatedProjectIds = new Set(live.flatMap((g) => (typeof g.project?.id === 'number' && isAutomatedOnly(g) ? [g.project.id] : [])));
            this.peerUnavailable = unavailable;
            this.errorText = '';
            this.status = 'ready';
        } catch (error) {
            if (mine !== this.#ticket) return;
            this.errorText = error instanceof Error ? error.message : String(error);
            this.status = 'error';
            return;
        }
        await Promise.all([this.readUnread(), this.readCounts(), this.readExtras(), this.readClosed()]);
    }

    /* did not answer */
    async #walk(query: (offset: number) => string): Promise<{ groups: HistoryGroup[]; peers: HistoryGroup[]; unavailable: string[] }> {
        const groups: HistoryGroup[] = [];
        let peers: HistoryGroup[] = [];
        let unavailable: string[] = [];
        let offset = 0;
        for (let pages = 0; pages < MAX_PAGES; pages += 1) {
            const page: HistoryPage = await this.#api.list(query(offset));
            if (page.state !== 'ok') throw new Error(this.#noDatastore);
            if (offset === 0) {
                peers = [...(page.peer_groups ?? [])];
                unavailable = (page.peer_unavailable ?? []).map((m) => m.host_label);
            }
            groups.push(...page.groups);
            if (page.next_offset === null || page.next_offset <= offset) break;
            offset = page.next_offset;
        }
        return { groups, peers, unavailable };
    }

    async readClosed(): Promise<void> {
        const mine = this.#ticket;
        try {
            const { groups, peers } = await this.#walk((offset) => closedQuery(offset, this.showHidden, this.showArchived));
            if (mine !== this.#ticket) return;
            this.closedRows = closedRowsFrom(
                groups.filter((g) => !g.project?.archived_at),
                peers.filter((g) => !g.project?.archived_at),
                this.#noProject,
            );
        } catch (error) {
            console.warn('CloudeOpscenter: closed sessions unavailable for the sessions page', error);
        }
    }

    async readUnread(): Promise<void> {
        try {
            const records = (await this.#readers.records()) as readonly RecordRow[] | null;
            if (!records) return;
            this.asleepUnreadSet = new Set(records.filter((r) => r.asleep === true && r.unread === true && r.session_uuid).map((r) => r.session_uuid as string));
        } catch (error) {
            console.warn('CloudeOpscenter: asleep unread unavailable for the sessions page', error);
        }
    }

    async readCounts(): Promise<void> {
        try {
            this.conversations = await this.#readers.counts();
        } catch (error) {
            console.warn('CloudeOpscenter: conversation counts unavailable for the sessions page', error);
        }
    }

    async readExtras(): Promise<void> {
        const r = this.#readers;
        const [u, l] = await Promise.allSettled([r.usage ? r.usage() : Promise.resolve(this.usage), r.latest ? r.latest() : Promise.resolve(this.latest)]);
        if (u.status === 'fulfilled') this.usage = u.value;
        else console.warn('CloudeOpscenter: session usage unavailable for the sessions page', u.reason);
        if (l.status === 'fulfilled') this.latest = l.value ?? {};
        else console.warn('CloudeOpscenter: latest lines unavailable for the sessions page', l.reason);
        this.pinTick += 1;
    }
}
