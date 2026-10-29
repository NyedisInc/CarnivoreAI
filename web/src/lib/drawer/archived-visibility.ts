/* could not */
import { drawerController } from './controller-ref';
import { readKey, writeKey } from './storage';
import { drawerEnv } from './env';
import { whenListingPushBooted } from '../listing-push/boot';

export const STORAGE_KEY = 'carnivore.session.sidebar.archived';
export const PREFERENCE_FIELD = 'sidebar_show_archived';
export const PANEL_ATTR = 'data-archived';
export const WATCHED_COLLECTIONS: readonly string[] = ['records', 'recent'];
export const WATCHED_TOPIC = 'projects';

export interface ArchivedProject {
    id: number;
    name: string;
    company_id: number | null;
    parent_project_id: number | null;
    pack_state?: string | null;
    moved_to_label?: string | null;
}

interface ArchivedGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => boolean): unknown;
        write?(field: string, value: boolean, local: () => void): Promise<unknown>;
    };
    API?: { listArchivedSessionRecords?(): Promise<unknown>; getProjects?(includeArchived?: boolean): Promise<unknown> };
    ListingPush?: { isLive?(): boolean; onChange?(fn: (names: string[]) => void): () => void };
    ResourcePush?: { onChange?(fn: (topics: string[]) => void): () => void };
}

interface RefreshTarget {
    refreshNow?(): Promise<void> | undefined;
    repaint(): void;
}

let shown = false;
let records: unknown[] | null = null;
let projects: ArchivedProject[] | null = null;
let stale = false;
let generation = 0;
let inFlight: Promise<void> | null = null;
let subscribed = false;

function g(): ArchivedGlobals {
    return drawerEnv() as ArchivedGlobals;
}

/*  hidden  */
function loadLocal(): boolean {
    try {
        return readKey(STORAGE_KEY) === '1';
    } catch {
        return false;
    }
}

export function archivedShown(): boolean {
    return shown;
}

/*  hidden  */
export function archivedRecords(): readonly unknown[] {
    return shown && records ? records : [];
}

/*  hidden  */
export function archivedProjects(): readonly ArchivedProject[] {
    return shown && projects ? projects : [];
}

export function archivedProjectsOf(got: unknown): ArchivedProject[] {
    if (!Array.isArray(got)) return [];
    const out: ArchivedProject[] = [];
    for (const raw of got) {
        const p = raw as { id?: unknown; name?: unknown; archived_at?: unknown; company_id?: unknown; parent_project_id?: unknown } | null;
        if (!p || !p.archived_at || typeof p.id !== 'number') continue;
        out.push({
            id: p.id,
            name: typeof p.name === 'string' ? p.name : '',
            company_id: typeof p.company_id === 'number' ? p.company_id : null,
            parent_project_id: typeof p.parent_project_id === 'number' ? p.parent_project_id : null,
        });
    }
    return out;
}

export function apply(): void {
    drawerController()?.panel?.setAttribute(PANEL_ATTR, shown ? 'shown' : 'hidden');
}

function redraw(): void {
    const ctrl = drawerController() as RefreshTarget | null;
    if (!ctrl) return;
    if (typeof ctrl.refreshNow === 'function') void ctrl.refreshNow();
    else ctrl.repaint();
}

export function refresh(): Promise<void> {
    if (!shown) return Promise.resolve();
    if (inFlight) return inFlight;
    const api = g().API;
    if (!api || typeof api.listArchivedSessionRecords !== 'function') return Promise.resolve();
    const at = generation;
    inFlight = (async () => {
        try {
            const readProjects = typeof api.getProjects === 'function' ? api.getProjects(true) : Promise.resolve([]);
            const [got, gotProjects] = await Promise.allSettled([api.listArchivedSessionRecords!(), readProjects]);
            if (at !== generation || !shown) return;
            stale = false;
            if (got.status === 'fulfilled') records = Array.isArray(got.value) ? got.value : [];
            else console.warn('SessionSidebarArchived: archived sessions unavailable:', (got.reason as Error)?.message);
            if (gotProjects.status === 'fulfilled') projects = archivedProjectsOf(gotProjects.value);
            else console.warn('SessionSidebarArchived: archived projects unavailable:', (gotProjects.reason as Error)?.message);
        } finally {
            inFlight = null;
        }
    })();
    return inFlight;
}

export function freshen(): Promise<void> {
    if (!shown) return Promise.resolve();
    const push = g().ListingPush;
    const live = !!push && typeof push.isLive === 'function' && push.isLive();
    if (records === null || stale || !live) return refresh();
    return Promise.resolve();
}

function subscribe(): void {
    if (subscribed) return;
    subscribed = true;
    const resources = g().ResourcePush;
    if (resources && typeof resources.onChange === 'function') {
        resources.onChange((topics) => {
            if (!shown || !topics.some((t) => t === WATCHED_TOPIC || t.startsWith(`${WATCHED_TOPIC}:`))) return;
            stale = true;
            redraw();
        });
    }
    whenListingPushBooted(() => {
        const push = g().ListingPush;
        if (!push || typeof push.onChange !== 'function') return;
        push.onChange((names) => {
            if (!shown || !names.some((n) => WATCHED_COLLECTIONS.includes(n))) return;
            stale = true;
            redraw();
        });
    });
}

export function setArchivedShown(next: boolean): boolean {
    if (next === shown) return false;
    shown = next;
    generation += 1;
    records = null;
    projects = null;
    const writeLocal = (): void => {
        try {
            writeKey(STORAGE_KEY, shown ? '1' : '0');
        } catch (err) {
            console.warn('SessionSidebarArchived: could not persist the archived toggle:', err);
        }
    };
    const bridge = g().PreferenceBridge;
    if (bridge && typeof bridge.write === 'function') {
        bridge.write(PREFERENCE_FIELD, shown, writeLocal).catch((err: unknown) => {
            console.warn('SessionSidebarArchived: could not share the archived toggle:', err);
        });
    } else {
        writeLocal();
    }
    apply();
    redraw();
    return true;
}

export function init(): void {
    const bridge = g().PreferenceBridge;
    const value = bridge && typeof bridge.read === 'function' ? bridge.read(PREFERENCE_FIELD, loadLocal) : loadLocal();
    const next = value === true;
    if (next !== shown) {
        shown = next;
        generation += 1;
        records = null;
        projects = null;
    }
    subscribe();
    apply();
}
