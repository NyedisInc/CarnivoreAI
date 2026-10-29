import {
    GROUP_KEYS, isBandOrderKey, isFoldKey, MAX_FOLDS,
} from './store-keys';
import { readKey, writeKey } from './storage';
import { viewClass, type ViewClass } from './view-class';

export const STORAGE_KEY = 'carnivore.session.sidebar.arrangement';

export const VERSION = 1;

export const MAX_REMEMBERED = 200;

export const MAX_SECTIONS = 32;

export const MAX_BAND_ORDERS = 100;

export type ArrangementStatus = 'default' | 'ok' | 'unreadable';

export interface ArrangementState {
    status: ArrangementStatus;
    reason: string | null;
    pinned: string[];
    order: string[];
    collapsed: string[];
    collapsedMobile?: string[];
    sections?: string[];
    ids: Record<string, string>;
    bands: Record<string, string[]>;
}

function emptyState(status: ArrangementStatus, reason: string | null): ArrangementState {
    return { status, reason, pinned: [], order: [], collapsed: [], ids: {}, bands: {} };
}

let state: ArrangementState = emptyState('default', null);

const savedListeners: Array<(s: ArrangementState) => void> = [];

export function onSaved(fn: (s: ArrangementState) => void): void {
    if (typeof fn === 'function') savedListeners.push(fn);
}

export function isNameArray(value: unknown): value is string[] {
    return Array.isArray(value) && value.every((n) => typeof n === 'string' && n.length > 0);
}

export function dedupe(names: readonly string[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const n of names) {
        if (seen.has(n)) continue;
        seen.add(n);
        out.push(n);
    }
    return out;
}

export function readCollapsed(value: unknown): string[] {
    if (value === undefined || value === null) return [];
    if (!isNameArray(value)) {
        console.warn('SessionSidebarArrangement: stored collapsed list is not a list of'
            + ' section names, treating every section as open');
        return [];
    }
    const kept = dedupe(value).filter(isFoldKey).slice(0, MAX_FOLDS);
    if (kept.length !== dedupe(value).length) {
        console.warn('SessionSidebarArrangement: dropped unknown collapsed section key(s)');
    }
    return kept;
}

export function readSections(value: unknown): string[] {
    if (!isNameArray(value)) {
        console.warn('SessionSidebarArrangement: stored section order is not a list of names, using the default order');
        return [];
    }
    return dedupe(value).slice(0, MAX_SECTIONS);
}

export function readBands(value: unknown): Record<string, string[]> {
    const out: Record<string, string[]> = {};
    if (value === undefined || value === null) return out;
    if (typeof value !== 'object' || Array.isArray(value)) {
        console.warn('SessionSidebarArrangement: stored band orders are not a map, ignoring them');
        return out;
    }
    const map = value as Record<string, unknown>;
    let dropped = false;
    for (const key of Object.keys(map)) {
        if (Object.keys(out).length >= MAX_BAND_ORDERS) { dropped = true; break; }
        const names = map[key];
        if (!isBandOrderKey(key) || !isNameArray(names)) { dropped = true; continue; }
        out[key] = dedupe(names).slice(0, MAX_REMEMBERED);
    }
    if (dropped) console.warn('SessionSidebarArrangement: dropped malformed band order(s)');
    return out;
}

export function readIds(value: unknown): Record<string, string> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const out: Record<string, string> = {};
    for (const [name, uuid] of Object.entries(value as Record<string, unknown>)) {
        if (typeof name === 'string' && name && typeof uuid === 'string' && uuid) out[name] = uuid;
    }
    return out;
}

function pruneIds(ids: Record<string, string>, names: readonly string[]): Record<string, string> {
    const out: Record<string, string> = {};
    for (const n of names) if (ids && ids[n]) out[n] = ids[n] as string;
    return out;
}

function unreadable(reason: string): ArrangementState {
    state = emptyState('unreadable', reason);
    return state;
}

export function load(): ArrangementState {
    let raw: string | null = null;
    try {
        raw = readKey(STORAGE_KEY);
    } catch {
        return unreadable('storage unavailable');
    }
    if (raw === null || raw === undefined || raw === '') {
        state = emptyState('default', null);
        return state;
    }
    let parsed: unknown = null;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return unreadable('stored value is not valid JSON');
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return unreadable('stored value is not an arrangement object');
    }
    const env = parsed as Record<string, unknown>;
    if (env.v !== VERSION) {
        return unreadable(`stored arrangement is version ${JSON.stringify(env.v)}, this app writes version ${VERSION}`);
    }
    if (!isNameArray(env.pinned) || !isNameArray(env.order)) {
        return unreadable('stored pin or order list is not a list of session names');
    }
    state = {
        status: 'ok',
        reason: null,
        pinned: dedupe(env.pinned).slice(0, MAX_REMEMBERED),
        order: dedupe(env.order).slice(0, MAX_REMEMBERED),
        collapsed: readCollapsed(env.collapsed),
        ...(env.collapsed_mobile === undefined || env.collapsed_mobile === null
            ? {} : { collapsedMobile: readCollapsed(env.collapsed_mobile) }),
        ...(env.sections === undefined || env.sections === null || !readSections(env.sections).length
            ? {} : { sections: readSections(env.sections) }),
        ids: readIds(env.ids),
        bands: readBands(env.bands),
    };
    return state;
}

export function current(): ArrangementState {
    return state;
}

export function save(
    pinned: readonly string[], order: readonly string[], collapsed?: readonly string[],
    ids?: Record<string, string>, bands?: Record<string, string[]>,
    collapsedMobile?: readonly string[] | null,
    sections?: readonly string[] | null,
): boolean {
    const nextPinned = dedupe(pinned).slice(0, MAX_REMEMBERED);
    const nextOrder = dedupe(order).slice(0, MAX_REMEMBERED);
    const nextCollapsed = readCollapsed(collapsed === undefined ? state.collapsed : collapsed);
    const nextBands = readBands(bands === undefined ? state.bands : bands);
    const nextMobile = collapsedMobile === undefined ? state.collapsedMobile
        : (collapsedMobile === null ? undefined : readCollapsed(collapsedMobile));
    const nextSections = sections === undefined ? state.sections
        : (sections === null || !sections.length ? undefined : readSections(sections));
    const bandNames = ([] as string[]).concat(...Object.values(nextBands));
    const nextIds = pruneIds(readIds(ids === undefined ? state.ids : ids),
        nextPinned.concat(nextOrder, bandNames));
    state = {
        status: 'ok',
        reason: null,
        pinned: nextPinned,
        order: nextOrder,
        collapsed: nextCollapsed,
        ...(nextMobile === undefined ? {} : { collapsedMobile: nextMobile }),
        ...(nextSections === undefined ? {} : { sections: nextSections }),
        ids: nextIds,
        bands: nextBands,
    };
    try {
        writeKey(STORAGE_KEY, JSON.stringify({
            v: VERSION,
            pinned: nextPinned,
            order: nextOrder,
            collapsed: nextCollapsed,
            ...(nextMobile === undefined ? {} : { collapsed_mobile: nextMobile }),
            ...(nextSections === undefined ? {} : { sections: nextSections }),
            ids: nextIds,
            bands: nextBands,
        }));
        return true;
    } catch (err) {
        console.warn('SessionSidebarArrangement: could not persist arrangement:', err);
        return false;
    } finally {
        for (const fn of savedListeners) {
            try {
                fn(state);
            } catch (e) {
                console.warn('SessionSidebarStore: save listener failed', e);
            }
        }
    }
}

function viewList(cls: ViewClass): string[] {
    return cls === 'mobile' ? (state.collapsedMobile || state.collapsed) : state.collapsed;
}

export function viewCollapsed(): string[] {
    return viewList(viewClass());
}

function saveView(cls: ViewClass, next: string[]): void {
    if (cls === 'mobile') save(state.pinned, state.order, undefined, undefined, undefined, next);
    else save(state.pinned, state.order, next);
}

export function isCollapsed(key: string): boolean {
    return viewCollapsed().indexOf(key) !== -1;
}

export function toggleCollapsed(key: string): boolean {
    if (!isFoldKey(key)) return false;
    const cls = viewClass();
    const list = viewList(cls);
    const next = list.indexOf(key) === -1;
    saveView(cls, next ? list.concat([key]) : list.filter((k) => k !== key));
    return next;
}

export function setCollapsedMany(add: readonly string[], remove: readonly string[]): boolean {
    const cls = viewClass();
    const list = viewList(cls);
    const drop = new Set(remove.filter(isFoldKey));
    const keep = list.filter((k) => !drop.has(k));
    const next = keep.concat(add.filter((k) => isFoldKey(k) && keep.indexOf(k) === -1));
    const same = next.length === list.length && next.every((k) => list.indexOf(k) !== -1);
    if (same) return false;
    saveView(cls, next);
    return true;
}

export function isPinned(name: string): boolean {
    return state.pinned.indexOf(name) !== -1;
}

export function bandOrder(key: string): string[] {
    const list = state.bands ? state.bands[key] : undefined;
    return Array.isArray(list) ? list : [];
}

export function saveBandOrder(key: string, names: readonly string[]): boolean {
    if (!isBandOrderKey(key)) return false;
    const bands: Record<string, string[]> = { [key]: names.slice() };
    for (const k of Object.keys(state.bands || {})) {
        if (k !== key) bands[k] = state.bands[k] as string[];
    }
    return save(state.pinned, state.order, undefined, undefined, bands);
}

export function saveSectionOrder(ids: readonly string[]): boolean {
    return save(state.pinned, state.order, undefined, undefined, undefined, undefined, ids);
}

export { GROUP_KEYS };
