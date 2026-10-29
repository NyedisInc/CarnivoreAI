import {
    attributionFailedDetail,
    listingDetail,
    projectsLoadFailed,
    recordsMalformedDetail,
    sessionsMalformedDetail,
} from '../../../../client/js/labels/session-listing.js';
import { loadFailedNotice } from '../../../../client/js/labels/recent-session.js';
import type { RecentSessionsPayload, Translate as RecentTranslate } from '../launchpad/recent';
import {
    loadAttribution,
    sortRunningSessionsByWork,
    type AttributionSnapshot,
} from './attribution';
import { hostWindow } from './env';
import { browserSessionHost, type SessionHost } from './host';
import { emptyListing, listingReasonFromError, statusFromError } from './listing';
import { createPoller, type Poller, type PollerDeps } from './poller';
import { loadRunningRows } from './running';
import type {
    ListingState,
    ProjectAuthority,
    ProjectPresenceRow,
    ProjectRow,
    RunningSessionRow,
    SessionRecord,
    Translate,
} from './types';

function dispatchReauthNeeded(): void {
    const w = hostWindow();
    if (!w) return;
    try {
        w.dispatchEvent(new CustomEvent('cloude:reauth-needed', {
            detail: { source: 'CloudeWeb.loadRunningSessions' },
        }));
    } catch (dispatchError) {
        console.warn('CloudeWeb: could not dispatch reauth event:', dispatchError);
    }
}


let recentPayload = $state<RecentSessionsPayload | null>(null);
let recentInFlight = $state(false);
let projects = $state<ProjectRow[]>([]);
let projectsListingOk = $state<boolean | null>(null);
let archivedFetchOk = $state<boolean | null>(null);
/* CANNOT DETERMINE */
let projectAuthority = $state<ProjectAuthority | null>(null);
let projectPresence = $state<Map<string, ProjectPresenceRow>>(new Map());
let runningSessions = $state<RunningSessionRow[]>([]);
let runningSessionsListing = $state<ListingState>(emptyListing());
let sessionAttribution = $state<Map<string, SessionRecord>>(new Map());
let sessionAttributionByInstance = $state<Map<string, SessionRecord>>(new Map());
/* could not */
let sessionAttributionAmbiguous = $state<Set<string>>(new Set());
let sessionAttributionListingOk = $state(true);
/* could not be read */
let sessionAttributionListingDetail = $state<string | null>(null);
let sessionRecords = $state<SessionRecord[]>([]);
let workStampByName = $state<Map<string, string>>(new Map());

let poller: Poller | null = null;
let runningGeneration = 0;
let newestRunningLoad: Promise<void> | null = null;

let host: SessionHost | null = null;

function activeHost(): SessionHost {
    if (!host) host = browserSessionHost();
    return host;
}

function startAttribution(t: Translate): Promise<AttributionSnapshot> {
    return loadAttribution(
        activeHost(), t, recordsMalformedDetail, attributionFailedDetail,
    );
}

function applyAttribution(snap: AttributionSnapshot): void {
    sessionAttribution = snap.byName;
    sessionAttributionByInstance = snap.byInstance;
    sessionAttributionAmbiguous = snap.ambiguous;
    sessionRecords = snap.records;
    workStampByName = snap.workStamps;
    sessionAttributionListingOk = snap.listingOk;
    sessionAttributionListingDetail = snap.listingDetail;
}

/* could not */
async function fetchRunningSessions(t: Translate, generation: number): Promise<void> {
    // could not
    const flags = (hostWindow() as unknown as {
        UIFlags?: { ensure?: unknown };
    } | undefined)?.UIFlags;
    if (flags && typeof flags.ensure === 'function') {
        (flags.ensure as () => void)();
    }
    const attribution = startAttribution(t);
    const { rows, listing } = await loadRunningRows({
        host: activeHost(),
        t,
        malformedDetail: sessionsMalformedDetail,
        detailFor: listingDetail,
        reasonFor: listingReasonFromError,
        statusFor: statusFromError,
        onReauth: dispatchReauthNeeded,
    });
    const attributionSnapshot = await attribution;
    if (generation !== runningGeneration) return newestRunningLoad ?? undefined;
    runningSessionsListing = listing;
    applyAttribution(attributionSnapshot);
    runningSessions = sortRunningSessionsByWork(rows.slice(), workStampByName);
}


export const sessionStore = {
    get recentPayload(): RecentSessionsPayload | null { return recentPayload; },
    get recentInFlight(): boolean { return recentInFlight; },
    get projects(): ProjectRow[] { return projects; },
    set projects(value: ProjectRow[]) { projects = value; },
    get projectsListingOk(): boolean | null { return projectsListingOk; },
    set projectsListingOk(value: boolean | null) { projectsListingOk = value; },
    get archivedFetchOk(): boolean | null { return archivedFetchOk; },
    set archivedFetchOk(value: boolean | null) { archivedFetchOk = value; },
    /* CANNOT DETERMINE */
    get projectAuthority(): ProjectAuthority | null { return projectAuthority; },
    set projectAuthority(value: ProjectAuthority | null) { projectAuthority = value; },
    get projectPresence(): Map<string, ProjectPresenceRow> { return projectPresence; },
    set projectPresence(value: Map<string, ProjectPresenceRow>) { projectPresence = value; },
    get runningSessions(): RunningSessionRow[] { return runningSessions; },
    set runningSessions(value: RunningSessionRow[]) { runningSessions = value; },
    get runningSessionsListing(): ListingState { return runningSessionsListing; },
    set runningSessionsListing(value: ListingState) { runningSessionsListing = value; },
    get sessionAttribution(): Map<string, SessionRecord> { return sessionAttribution; },
    set sessionAttribution(value: Map<string, SessionRecord>) { sessionAttribution = value; },
    get sessionAttributionByInstance(): Map<string, SessionRecord> {
        return sessionAttributionByInstance;
    },
    set sessionAttributionByInstance(value: Map<string, SessionRecord>) {
        sessionAttributionByInstance = value;
    },
    /* could not */
    get sessionAttributionAmbiguous(): Set<string> { return sessionAttributionAmbiguous; },
    set sessionAttributionAmbiguous(value: Set<string>) { sessionAttributionAmbiguous = value; },
    get sessionAttributionListingOk(): boolean { return sessionAttributionListingOk; },
    set sessionAttributionListingOk(value: boolean) { sessionAttributionListingOk = value; },
    get sessionAttributionListingDetail(): string | null {
        return sessionAttributionListingDetail;
    },
    set sessionAttributionListingDetail(value: string | null) {
        sessionAttributionListingDetail = value;
    },
    get sessionRecords(): SessionRecord[] { return sessionRecords; },
    set sessionRecords(value: SessionRecord[]) { sessionRecords = value; },
    get workStampByName(): Map<string, string> { return workStampByName; },
    set workStampByName(value: Map<string, string>) { workStampByName = value; },
    get polling(): boolean { return !!poller && poller.running; },

    useHost(next: SessionHost | null): void {
        host = next;
    },

    async refreshRecent(
        fetchRecent: (includeArchived: boolean) => Promise<RecentSessionsPayload>,
        includeArchived: boolean,
        t: RecentTranslate,
    ): Promise<void> {
        recentInFlight = true;
        try {
            const payload = await fetchRecent(!!includeArchived);
            recentPayload = {
                // did not answer
                state: (payload && payload.state) || 'probe_unavailable',
                sessions: (payload && payload.sessions) || [],
                notice: (payload && payload.notice) || null,
            };
        } catch (error) {
            console.warn('CloudeWeb: failed to load recent sessions:', error);
            recentPayload = {
                state: 'probe_unavailable',
                sessions: [],
                notice: loadFailedNotice(error, t),
            };
        } finally {
            recentInFlight = false;
        }
    },

    async loadProjectAuthority(): Promise<void> {
        try {
            projectAuthority = await activeHost().getProjectsAuthority();
        } catch (error) {
            console.warn('CloudeWeb: failed to load project authority:', error);
            projectAuthority = null;
        }
    },

    async loadProjectPresence(): Promise<void> {
        const next = new Map<string, ProjectPresenceRow>();
        try {
            const result = await activeHost().getProjectsPresence();
            if (result && result.status === 'ok' && Array.isArray(result.projects)) {
                for (const row of result.projects) {
                    if (row && row.raw_path) next.set(row.raw_path, row);
                    if (row && row.root) next.set(row.root, row);
                }
            }
        } catch (error) {
            console.warn('CloudeWeb: failed to load project presence:', error);
        }
        projectPresence = next;
    },

    async loadProjects(
        includeArchived: boolean,
        t: Translate,
    ): Promise<{ ok: boolean; error: string | null }> {
        let sidecars: Promise<unknown> = Promise.resolve();
        try {
            const listing = activeHost().getProjects(includeArchived);
            sidecars = Promise.all([
                this.loadProjectPresence(),
                this.loadProjectAuthority(),
            ]);
            projects = await listing;
            projectsListingOk = true;
            archivedFetchOk = includeArchived ? true : null;
            await sidecars;
            return { ok: true, error: null };
        } catch (error) {
            projectsListingOk = false;
            archivedFetchOk = includeArchived ? false : null;
            await sidecars;
            console.error('CloudeWeb: failed to load projects:', error);
            return { ok: false, error: projectsLoadFailed(error, t) };
        }
    },

    async loadSessionAttribution(t: Translate): Promise<void> {
        applyAttribution(await startAttribution(t));
    },

    loadRunningSessions(t: Translate): Promise<void> {
        const load = fetchRunningSessions(t, ++runningGeneration);
        newestRunningLoad = load;
        return load;
    },

    startPolling(deps: PollerDeps): void {
        if (!poller) {
            const push = (globalThis as { ListingPush?: PollerDeps['push'] }).ListingPush ?? null;
            poller = createPoller({ push, ...deps });
        }
        poller.start();
    },

    stopPolling(): void {
        if (!poller) return;
        poller.stop();
        poller = null;
    },

    reset(): void {
        ++runningGeneration;
        newestRunningLoad = null;
        this.stopPolling();
        recentPayload = null;
        recentInFlight = false;
        projects = [];
        projectsListingOk = null;
        archivedFetchOk = null;
        projectAuthority = null;
        projectPresence = new Map();
        runningSessions = [];
        runningSessionsListing = emptyListing();
        sessionAttribution = new Map();
        sessionAttributionByInstance = new Map();
        sessionAttributionAmbiguous = new Set();
        sessionAttributionListingOk = true;
        sessionAttributionListingDetail = null;
        sessionRecords = [];
        workStampByName = new Map();
        host = null;
    },
};
