import * as G from './group-store';
import * as S from './store';
import { drawerController } from './controller-ref';
import { readKey } from './storage';
import { drawerEnv } from './env';

export const FIELD = 'drawer_arrangement';
export const PLACEHOLDER = '@';
export const WRITE_DELAY = 400;
const RETRY_DELAY = 300;
export const BACKSTOP_MS = 5000;
const MAX_BACKOFF = 60000;

export interface SharedArrangement {
    v: 1;
    pinned: string[];
    order: string[];
    bands: Record<string, string[]>;
    collapsed: string[];
    projects_open: boolean | null;
    mobile?: { collapsed: string[] };
    sections?: string[];
}

export interface LocalArrangement {
    pinned?: string[];
    order?: string[];
    bands?: Record<string, string[]>;
    collapsed?: string[];
    collapsedMobile?: string[] | null;
    sections?: string[];
    ids?: Record<string, string>;
    status?: string;
}

export interface SyncRow {
    name?: string;
    session_uuid?: string | null;
}

interface PreferencesApi {
    HYDRATED: unknown;
    COMMITTED: unknown;
    status(): unknown;
    committedValue(field: string): unknown;
    set(field: string, value: unknown): Promise<{ status: string }>;
    discardLocal?(field: string): void;
    subscribe?(fn: (name: string, value: unknown, record: { state?: unknown } | null) => void): void;
    hydrate(api: unknown): unknown;
}

interface AppEventsApi {
    isConnected?(): boolean;
    subscribe?(fn: (frame: unknown) => void): void;
}

interface SyncGlobals {
    Preferences?: PreferencesApi;
    AppEvents?: AppEventsApi;
    API?: unknown;
    CloudeI18n?: { t(key: string): string };
    SessionSidebarRowDrag?: { isDragging?(): boolean };
    SessionSidebarSectionDrag?: { isDragging?(): boolean };
    SessionSidebarGroupActions?: { refresh?(): unknown };
}

function g(): SyncGlobals {
    return drawerEnv() as SyncGlobals;
}

export function empty(): SharedArrangement {
    return { v: 1, pinned: [], order: [], bands: {}, collapsed: [], projects_open: null };
}

function strings(list: unknown): string[] {
    if (!Array.isArray(list)) return [];
    const seen = new Set<string>();
    return list.filter((x): x is string => typeof x === 'string' && !!x && !seen.has(x) && !!seen.add(x));
}

export function normalise(value: unknown): SharedArrangement | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const v = value as Record<string, unknown>;
    const bands: Record<string, string[]> = {};
    const raw = v.bands && typeof v.bands === 'object' ? v.bands as Record<string, unknown> : {};
    for (const key of Object.keys(raw).sort()) bands[key] = strings(raw[key]);
    const mobile = v.mobile && typeof v.mobile === 'object' && !Array.isArray(v.mobile)
        ? { collapsed: strings((v.mobile as Record<string, unknown>).collapsed) } : null;
    const sections = strings(v.sections);
    return {
        v: 1,
        pinned: strings(v.pinned),
        order: strings(v.order),
        bands,
        collapsed: strings(v.collapsed),
        projects_open: typeof v.projects_open === 'boolean' ? v.projects_open : null,
        ...(mobile ? { mobile } : {}),
        ...(sections.length ? { sections } : {}),
    };
}

function same(a: unknown, b: unknown): boolean {
    return JSON.stringify(a) === JSON.stringify(b);
}

function index(rows: readonly SyncRow[]): { byName: Map<string, SyncRow>; byUuid: Map<string, string> } {
    const byName = new Map<string, SyncRow>();
    const byUuid = new Map<string, string>();
    for (const r of Array.isArray(rows) ? rows : []) {
        if (!r || !r.name) continue;
        byName.set(r.name, r);
        if (r.session_uuid && !byUuid.has(r.session_uuid)) byUuid.set(r.session_uuid, r.name);
    }
    return { byName, byUuid };
}

function isLayout(name: unknown): boolean {
    return typeof name === 'string' && name.indexOf('layout:') === 0;
}

export function toServer(
    local: LocalArrangement | null | undefined, rows: readonly SyncRow[], projectsOpen: boolean | null,
): SharedArrangement {
    const ix = index(rows);
    const ids = (local && local.ids) || {};
    const uuidOf = (name: string): string | null => (isLayout(name) ? name
        : (ids[name] || (ix.byName.get(name) || {}).session_uuid || null));
    const map = (names: readonly string[] | undefined): string[] => strings((names || []).map(uuidOf));
    const sessionsOnly = (names: readonly string[] | undefined): string[] => (names || []).filter((n) => !isLayout(n));
    const bands: Record<string, string[]> = {};
    const localBands = (local && local.bands) || {};
    for (const key of Object.keys(localBands)) bands[key] = map(sessionsOnly(localBands[key]));
    return normalise({
        pinned: map(local?.pinned),
        order: map(sessionsOnly(local?.order)),
        bands,
        collapsed: (local && local.collapsed) || [],
        projects_open: projectsOpen,
        mobile: local && Array.isArray(local.collapsedMobile) ? { collapsed: local.collapsedMobile } : null,
        sections: local && Array.isArray(local.sections) ? local.sections : [],
    }) as SharedArrangement;
}

export function fromServer(
    value: SharedArrangement, local: LocalArrangement | null | undefined, rows: readonly SyncRow[],
): {
    pinned: string[]; order: string[]; bands: Record<string, string[]>; collapsed: string[];
    collapsedMobile: string[] | null; sections: string[] | null; ids: Record<string, string>;
} {
    const ix = index(rows);
    const known = (local && local.ids) || {};
    const byUuid = new Map(ix.byUuid);
    for (const name of Object.keys(known)) {
        const u = known[name] as string;
        if (!byUuid.has(u)) byUuid.set(u, name);
    }
    const ids: Record<string, string> = {};
    const nameOf = (uuid: string): string => {
        if (isLayout(uuid)) {
            ids[uuid] = uuid;
            return uuid;
        }
        const name = byUuid.get(uuid) || (PLACEHOLDER + uuid);
        ids[name] = uuid;
        return name;
    };
    const hasUuid = (name: string): boolean => isLayout(name)
        || !!(known[name] || (ix.byName.get(name) || {}).session_uuid);
    const keepLocal = (names: readonly string[] | undefined): string[] => (names || []).filter((n) => !hasUuid(n));
    const merge = (uuids: readonly string[], localNames: readonly string[] | undefined): string[] =>
        strings(uuids.map(nameOf).concat(keepLocal(localNames)));
    const localBands = (local && local.bands) || {};
    const bands: Record<string, string[]> = {};
    for (const key of new Set(Object.keys(value.bands).concat(Object.keys(localBands)))) {
        const list = merge(value.bands[key] || [], localBands[key]);
        if (list.length || value.bands[key]) bands[key] = list;
    }
    return {
        pinned: merge(value.pinned, local?.pinned),
        order: merge(value.order, local?.order),
        bands,
        collapsed: value.collapsed.slice(),
        collapsedMobile: value.mobile ? value.mobile.collapsed.slice() : null,
        sections: value.sections ? value.sections.slice() : null,
        ids,
    };
}

export function merge3(
    base: SharedArrangement | null, mine: SharedArrangement, theirs: SharedArrangement,
): SharedArrangement {
    const b = base || empty();
    const pick = <K extends keyof SharedArrangement>(key: K): SharedArrangement[K] =>
        (same(mine[key], b[key]) ? theirs[key] : mine[key]);
    const bands: Record<string, string[]> = { ...theirs.bands };
    for (const key of new Set(Object.keys(mine.bands).concat(Object.keys(b.bands)))) {
        if (same(mine.bands[key], b.bands[key])) continue;
        if (mine.bands[key]) bands[key] = mine.bands[key] as string[];
        else delete bands[key];
    }
    return normalise({
        pinned: pick('pinned'),
        order: pick('order'),
        bands,
        collapsed: pick('collapsed'),
        projects_open: pick('projects_open'),
        mobile: pick('mobile') || null,
        sections: pick('sections') || [],
    }) as SharedArrangement;
}

let synced: SharedArrangement | null = null;
let seeded: { collapsed: string[] } | null = null;
let projectsIntent: boolean | null = null;
let applying = false;
let dirty = false;
let inflight = false;
let writeTimer: ReturnType<typeof setTimeout> | null = null;
let heldTimer: ReturnType<typeof setTimeout> | null = null;
let lastRows: SyncRow[] = [];
let lastBackstop = 0;
let failures = 0;
let started = false;
let storesHooked = false;

function prefs(): PreferencesApi | null {
    const p = g().Preferences;
    return p && typeof p.set === 'function' && typeof p.committedValue === 'function' ? p : null;
}

function hydrated(api: PreferencesApi | null): api is PreferencesApi {
    return !!api && api.status() === api.HYDRATED;
}

function localProjectsOpen(): boolean | null {
    let raw: string | null = null;
    try {
        raw = readKey(G.PROJECTS_OPEN_KEY);
    } catch {
        return null;
    }
    return raw === '1' ? true : raw === '0' ? false : null;
}

function current(): SharedArrangement {
    const open = projectsIntent !== null ? projectsIntent : (synced ? synced.projects_open : null);
    return toServer(S.current(), lastRows, open);
}

function announce(key: string): void {
    const i18n = g().CloudeI18n;
    const text = i18n && typeof i18n.t === 'function' ? i18n.t(key) : key;
    const region = typeof document !== 'undefined' && document.getElementById('session-sidebar-live');
    if (region) region.textContent = text;
    console.log(`[SessionSidebarSync] ${key}`);
}

function dragging(): boolean {
    const { SessionSidebarRowDrag: rows, SessionSidebarSectionDrag: sections } = g();
    return !!((rows && typeof rows.isDragging === 'function' && rows.isDragging())
        || (sections && typeof sections.isDragging === 'function' && sections.isDragging()));
}

function applyValue(value: SharedArrangement): void {
    applying = true;
    try {
        const st = S.current();
        const next = fromServer(value, st.status === 'ok' ? st : {}, lastRows);
        S.save(next.pinned, next.order, next.collapsed, next.ids, next.bands, next.collapsedMobile, next.sections);
        if (typeof value.projects_open === 'boolean' && G.isProjectsOpen() !== value.projects_open) {
            G.setProjectsOpen(value.projects_open);
        }
    } finally {
        applying = false;
    }
    const sidebar = drawerController();
    if (sidebar && sidebar.isOpen) sidebar.repaint();
}

function mergeOver(base: SharedArrangement | null, mine: SharedArrangement, theirs: SharedArrangement): SharedArrangement {
    if (seeded && theirs.mobile && same(mine.mobile, seeded)) {
        seeded = null;
        return merge3(base, { ...mine, mobile: theirs.mobile }, theirs);
    }
    return merge3(base, mine, theirs);
}

export function followCommitted(): void {
    const api = prefs();
    if (!hydrated(api) || synced === null || inflight) return;
    const theirs = normalise(api.committedValue(FIELD));
    if (theirs === null || same(theirs, synced)) return;
    if (dragging()) {
        if (heldTimer === null) {
            heldTimer = setTimeout(() => {
                heldTimer = null;
                followCommitted();
            }, RETRY_DELAY);
        }
        return;
    }
    const shown = dirty ? mergeOver(synced, current(), theirs) : theirs;
    synced = theirs;
    applyValue(shown);
}

export function noteLocal(): void {
    if (applying) return;
    dirty = true;
    scheduleWrite(WRITE_DELAY);
}

function scheduleWrite(delay: number): void {
    if (writeTimer !== null) clearTimeout(writeTimer);
    writeTimer = setTimeout(() => {
        writeTimer = null;
        void flush();
    }, delay);
}

function settleIntent(sent: SharedArrangement): void {
    if (projectsIntent === sent.projects_open) projectsIntent = null;
}

export async function flush(): Promise<void> {
    const api = prefs();
    if (!dirty || !api) return;
    if (inflight || !hydrated(api) || synced === null || dragging()) {
        scheduleWrite(RETRY_DELAY * 4);
        return;
    }
    followCommitted();
    dirty = false;
    const base = synced;
    const mine = current();
    if (same(mine, base)) return;
    inflight = true;
    try {
        const result = await api.set(FIELD, mine);
        if (result.status === 'committed' || result.status === 'unchanged') {
            synced = mine;
            seeded = null;
            settleIntent(mine);
            failures = 0;
        } else if (result.status === 'stale_revision') {
            await resolveConflict(api, base, mine);
        } else {
            dirty = true;
            failures += 1;
        }
    } finally {
        inflight = false;
    }
    if (dirty) scheduleWrite(Math.min(MAX_BACKOFF, RETRY_DELAY * 4 * Math.pow(2, failures)));
}

async function resolveConflict(api: PreferencesApi, base: SharedArrangement, mine: SharedArrangement): Promise<void> {
    if (dragging()) {
        dirty = true;
        return;
    }
    const theirs = normalise(api.committedValue(FIELD)) || empty();
    const merged = mergeOver(base, mine, theirs);
    applyValue(merged);
    const again = await api.set(FIELD, merged);
    if (again.status === 'committed' || again.status === 'unchanged') {
        synced = merged;
        settleIntent(merged);
        announce('sidebar.sync.merged');
        return;
    }
    if (again.status === 'stale_revision') {
        if (typeof api.discardLocal === 'function') api.discardLocal(FIELD);
        projectsIntent = null;
        announce('sidebar.sync.lost');
        if (dragging()) return;
        const latest = normalise(api.committedValue(FIELD)) || empty();
        synced = latest;
        applyValue(latest);
        return;
    }
    synced = theirs;
    dirty = true;
}

function hasAny(value: SharedArrangement): boolean {
    return value.pinned.length > 0 || value.order.length > 0 || value.collapsed.length > 0
        || Object.keys(value.bands).length > 0 || value.projects_open !== null;
}

function seedMobile(list: readonly string[]): void {
    const st = S.current();
    seeded = { collapsed: list.slice() };
    S.save(st.pinned, st.order, undefined, undefined, undefined, list);
}

export async function hydrate(): Promise<void> {
    const api = prefs();
    if (!hydrated(api) || synced !== null || inflight || dragging()) return;
    const theirs = normalise(api.committedValue(FIELD));
    if (theirs !== null) {
        synced = theirs;
        const own = S.current().status === 'ok' ? S.current().collapsedMobile : undefined;
        applyValue(theirs);
        if (!theirs.mobile) seedMobile(own || theirs.collapsed);
        return;
    }
    synced = empty();
    const st = S.current();
    const mine = toServer(st && st.status === 'ok' ? st : {}, lastRows, localProjectsOpen());
    if (!hasAny(mine)) return;
    if (!mine.mobile) mine.mobile = { collapsed: mine.collapsed.slice() };
    inflight = true;
    try {
        const result = await api.set(FIELD, mine);
        if (result.status === 'committed' || result.status === 'unchanged') {
            synced = mine;
            applyValue(mine);
        } else if (result.status === 'stale_revision') {
            if (typeof api.discardLocal === 'function') api.discardLocal(FIELD);
            if (!dragging()) {
                const latest = normalise(api.committedValue(FIELD)) || empty();
                synced = latest;
                applyValue(latest);
            }
        } else {
            synced = null;
        }
    } finally {
        inflight = false;
    }
}

function refreshGroups(): void {
    const actions = g().SessionSidebarGroupActions;
    if (actions && typeof actions.refresh === 'function') actions.refresh();
}

export function noteRows(rows: readonly SyncRow[]): void {
    lastRows = Array.isArray(rows) ? rows.slice() as SyncRow[] : [];
    const api = prefs();
    if (!hydrated(api)) return;
    if (synced === null) {
        void hydrate();
        return;
    }
    followCommitted();
    const events = g().AppEvents;
    const live = !!events && typeof events.isConnected === 'function' && events.isConnected();
    const now = Date.now();
    if (live || now - lastBackstop < BACKSTOP_MS) return;
    lastBackstop = now;
    Promise.resolve(api.hydrate(g().API)).then(followCommitted, (err: unknown) => {
        console.warn('[SessionSidebarSync] backstop re-read failed', (err as Error)?.message || err);
    });
    refreshGroups();
}

function onFrame(frame: unknown): void {
    if (!frame || typeof frame !== 'object') return;
    const f = frame as { type?: string; reason?: string };
    if ((f.type === 'sessions.changed' && f.reason === 'groups') || f.type === 'events.hello') refreshGroups();
}

export function start(): void {
    if (started) return;
    started = true;
    if (!storesHooked) {
        storesHooked = true;
        S.onSaved(noteLocal);
        G.onProjectsOpenChange((open) => {
            if (applying) return;
            projectsIntent = !!open;
            noteLocal();
        });
    }
    const api = prefs();
    if (api && typeof api.subscribe === 'function') {
        api.subscribe((name, _value, record) => {
            if (name !== FIELD || !record || record.state !== api.COMMITTED || inflight) return;
            followCommitted();
        });
    }
    const events = g().AppEvents;
    if (events && typeof events.subscribe === 'function') events.subscribe(onFrame);
}

export function reset(): void {
    synced = null;
    seeded = null;
    projectsIntent = null;
    applying = false;
    dirty = false;
    inflight = false;
    lastRows = [];
    lastBackstop = 0;
    started = false;
    failures = 0;
    if (writeTimer !== null) clearTimeout(writeTimer);
    if (heldTimer !== null) clearTimeout(heldTimer);
    writeTimer = null;
    heldTimer = null;
}

export function isApplying(): boolean {
    return applying;
}
