import type { DynamicTabDef } from '../dynamic-tabs/types';
import { drawerEnv } from '../drawer/env';
import { whenLegacyBootComplete } from '../legacy-boot';
import { FEED_WINDOWS, RATE_UNITS, type FeedWindow, type RateUnit } from '../stats-feed/types';
import { readChoice, writeChoice } from '../ui/prefs.svelte';


export const DRAWER_TABS = ['menu', 'agents'] as const;
export type DrawerTab = (typeof DRAWER_TABS)[number];

export const DEFAULT_DRAWER_TAB: DrawerTab = 'agents';

export const DRAWER_TABBODY_ID = 'session-sidebar-tabbody';

export const DRAWER_AREA_BAR_ID = 'session-sidebar-area-bar';

export const DRAWER_TAB_STORAGE_KEY = 'carnivore.session.sidebar.tab';

export const DRAWER_STATS_ID = 'session-sidebar-stats';

export const DRAWER_STATS_RATE_KEY = 'carnivore.session.sidebar.statsRate';
export const DRAWER_STATS_WINDOW_KEY = 'carnivore.session.sidebar.statsWindow';
export const DRAWER_STATS_RATE_PREF_FIELD = 'stats_bar_rate';
export const DRAWER_STATS_WINDOW_PREF_FIELD = 'stats_bar_window';

interface StatsPrefsGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => unknown): unknown;
        write?(field: string, value: string, local: () => void): Promise<unknown>;
        follow?(field: string, apply: (value: unknown) => void): () => void;
    };
    Preferences?: {
        HYDRATED?: unknown;
        status?(): unknown;
        get?(field: string, fallback?: unknown): unknown;
        set?(field: string, value: unknown): Promise<unknown>;
        subscribe?(fn: (name: string, value: unknown) => void): () => void;
    };
}

function validChoice<T extends string>(value: unknown, allowed: readonly T[]): T | null {
    return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? value as T : null;
}

function readSharedStatsChoice<T extends string>(field: string, allowed: readonly T[]): T | null {
    const env = drawerEnv() as StatsPrefsGlobals;
    const bridge = env.PreferenceBridge;
    if (bridge && typeof bridge.read === 'function') {
        return validChoice(bridge.read(field, () => null), allowed);
    }
    const prefs = env.Preferences;
    if (!prefs || typeof prefs.get !== 'function') return null;
    if (typeof prefs.status === 'function' && prefs.status() !== (prefs.HYDRATED ?? 'hydrated')) return null;
    return validChoice(prefs.get(field, undefined), allowed);
}

function writeSharedStatsChoice(field: string, storageKey: string, value: string): void {
    const writeLocal = (): void => writeChoice(storageKey, value);
    const env = drawerEnv() as StatsPrefsGlobals;
    const bridge = env.PreferenceBridge;
    if (bridge && typeof bridge.write === 'function') {
        bridge.write(field, value, writeLocal).catch((err: unknown) => {
            console.warn(`DrawerStats: could not share ${field}:`, err);
        });
        return;
    }
    writeLocal();
    const prefs = env.Preferences;
    if (prefs && typeof prefs.set === 'function'
        && (typeof prefs.status !== 'function' || prefs.status() === (prefs.HYDRATED ?? 'hydrated'))) {
        prefs.set(field, value).catch((err: unknown) => {
            console.warn(`DrawerStats: could not share ${field}:`, err);
        });
    }
}

export function readStatsRate(): RateUnit {
    return readSharedStatsChoice(DRAWER_STATS_RATE_PREF_FIELD, RATE_UNITS)
        ?? readChoice(DRAWER_STATS_RATE_KEY, RATE_UNITS, 'min');
}

export function writeStatsRate(value: RateUnit): void {
    writeSharedStatsChoice(DRAWER_STATS_RATE_PREF_FIELD, DRAWER_STATS_RATE_KEY, value);
}

export function readStatsWindow(): FeedWindow {
    return readSharedStatsChoice(DRAWER_STATS_WINDOW_PREF_FIELD, FEED_WINDOWS)
        ?? readChoice(DRAWER_STATS_WINDOW_KEY, FEED_WINDOWS, '1h');
}

export function writeStatsWindow(value: FeedWindow): void {
    writeSharedStatsChoice(DRAWER_STATS_WINDOW_PREF_FIELD, DRAWER_STATS_WINDOW_KEY, value);
}

export function followStatsPrefs(
    handlers: { onRate?: (rate: RateUnit) => void; onWindow?: (win: FeedWindow) => void },
    target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
    const applyRate = (raw: unknown): void => {
        const next = validChoice(raw, RATE_UNITS);
        if (next === null) return;
        writeChoice(DRAWER_STATS_RATE_KEY, next);
        handlers.onRate?.(next);
    };
    const applyWindow = (raw: unknown): void => {
        const next = validChoice(raw, FEED_WINDOWS);
        if (next === null) return;
        writeChoice(DRAWER_STATS_WINDOW_KEY, next);
        handlers.onWindow?.(next);
    };
    const syncHydrated = (): void => {
        const rate = readSharedStatsChoice(DRAWER_STATS_RATE_PREF_FIELD, RATE_UNITS);
        if (rate !== null) applyRate(rate);
        const win = readSharedStatsChoice(DRAWER_STATS_WINDOW_PREF_FIELD, FEED_WINDOWS);
        if (win !== null) applyWindow(win);
    };
    syncHydrated();

    const stops: Array<() => void> = [];
    const env = drawerEnv() as StatsPrefsGlobals;
    const bridge = env.PreferenceBridge;
    if (bridge && typeof bridge.follow === 'function') {
        stops.push(bridge.follow(DRAWER_STATS_RATE_PREF_FIELD, applyRate));
        stops.push(bridge.follow(DRAWER_STATS_WINDOW_PREF_FIELD, applyWindow));
    } else if (env.Preferences && typeof env.Preferences.subscribe === 'function') {
        stops.push(env.Preferences.subscribe((name, value) => {
            if (name === DRAWER_STATS_RATE_PREF_FIELD) applyRate(value);
            else if (name === DRAWER_STATS_WINDOW_PREF_FIELD) applyWindow(value);
        }));
    }
    let stopped = false;
    whenLegacyBootComplete(target, () => {
        if (!stopped) syncHydrated();
    });
    return () => {
        stopped = true;
        for (const stop of stops) stop();
    };
}

export const DRAWER_LIST_ID = 'session-sidebar-list';

export const DRAWER_SEARCH_ID = 'session-sidebar-search';

export const DRAWER_DEEP_SEARCH_KEY = 'carnivore.session.sidebar.deepSearch';

export const DRAWER_SEARCH_MODE_KEY = 'carnivore.session.sidebar.searchMode';

export const DRAWER_DEEP_ACTIVE_CLASS = 'drawer-deep-search';

export const QUESTIONS_TAB = 'questions';

export const DRAWER_LEDGER_ID = 'session-sidebar-ledger';

export type NewSessionKind = 'agent' | 'terminal' | 'browser';

export const NEW_SESSION_BROWSER_ENABLED: boolean = true;

export function newSessionKinds(): readonly NewSessionKind[] {
    return NEW_SESSION_BROWSER_ENABLED ? ['agent', 'terminal', 'browser'] : ['agent', 'terminal'];
}

export function applyDrawerTab(tab: string, defs: readonly DynamicTabDef[], doc: Document = document): void {
    let componentBody = false;
    for (const def of defs) {
        if ('component' in def.body) {
            if (def.id === tab) componentBody = true;
            continue;
        }
        for (const id of def.body.containers) {
            const el = doc.getElementById(id);
            if (el) el.hidden = def.id !== tab;
        }
    }
    const body = doc.getElementById(DRAWER_TABBODY_ID);
    if (body) body.hidden = !componentBody;
}
