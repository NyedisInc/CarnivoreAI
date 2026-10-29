/*  hidden
 */
import { readKey, writeKey } from './storage';
import { drawerEnv } from './env';
import { viewClass, type ViewClass } from './view-class';

export const STORAGE_KEY = 'carnivore.session.sidebar.stats';
export const MOBILE_STORAGE_KEY = 'carnivore.session.sidebar.stats.mobile';
export const PREFERENCE_FIELD = 'sidebar_show_stats';
export const MOBILE_PREFERENCE_FIELD = 'sidebar_show_stats_mobile';

interface BridgeGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => boolean | null): unknown;
        write?(field: string, value: boolean, local: () => void): Promise<unknown>;
    };
}

const view = $state<{ shown: boolean | null }>({ shown: null });

function loadLocal(key: string): boolean | null {
    try {
        const raw = readKey(key);
        return raw === '1' ? true : raw === '0' ? false : null;
    } catch {
        return null;
    }
}

function chosen(field: string, key: string): boolean | null {
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    const value = bridge && typeof bridge.read === 'function' ? bridge.read(field, () => loadLocal(key)) : loadLocal(key);
    return typeof value === 'boolean' ? value : null;
}

const ABSENT_SHOWN = false;

function loadFor(cls: ViewClass): boolean {
    const desktop = chosen(PREFERENCE_FIELD, STORAGE_KEY);
    if (cls === 'mobile') return chosen(MOBILE_PREFERENCE_FIELD, MOBILE_STORAGE_KEY) ?? desktop ?? ABSENT_SHOWN;
    return desktop ?? ABSENT_SHOWN;
}

export function statsShown(): boolean | null {
    return view.shown;
}

export function setStatsShown(next: boolean): boolean {
    if (next === view.shown) return false;
    view.shown = next;
    const mobile = viewClass() === 'mobile';
    const field = mobile ? MOBILE_PREFERENCE_FIELD : PREFERENCE_FIELD;
    const writeLocal = (): void => {
        try {
            writeKey(mobile ? MOBILE_STORAGE_KEY : STORAGE_KEY, next ? '1' : '0');
        } catch (err) {
            console.warn('SessionSidebarStats: could not persist the stats toggle:', err);
        }
    };
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    if (bridge && typeof bridge.write === 'function') {
        bridge.write(field, next, writeLocal).catch((err: unknown) => {
            console.warn('SessionSidebarStats: could not share the stats toggle:', err);
        });
    } else {
        writeLocal();
    }
    return true;
}

export function init(): void {
    const next = loadFor(viewClass());
    if (next !== view.shown) view.shown = next;
}
