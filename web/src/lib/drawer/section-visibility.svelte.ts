import { drawerController } from './controller-ref';
import { readKey, writeKey } from './storage';
import { drawerEnv } from './env';
import { viewClass, type ViewClass } from './view-class';

const ABSENT_SHOWN = true;

export type OptionalSection = 'open' | 'sleeping';

export const OPTIONAL_SECTIONS: readonly OptionalSection[] = ['open', 'sleeping'];

export const STORAGE_KEYS: Readonly<Record<OptionalSection, string>> = {
    open: 'carnivore.session.sidebar.list_open',
    sleeping: 'carnivore.session.sidebar.list_sleeping',
};

const MOBILE_LOCAL_SUFFIX = '.mobile';
const MOBILE_FIELD_SUFFIX = '_mobile';

export function preferenceField(id: OptionalSection, cls: ViewClass): string {
    return `sidebar_list_${id}${cls === 'mobile' ? MOBILE_FIELD_SUFFIX : ''}`;
}

function storageKey(id: OptionalSection, cls: ViewClass): string {
    return STORAGE_KEYS[id] + (cls === 'mobile' ? MOBILE_LOCAL_SUFFIX : '');
}

interface BridgeGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => boolean | null): unknown;
        write?(field: string, value: boolean, local: () => void): Promise<unknown>;
    };
}

const view = $state<Record<OptionalSection, boolean>>({ open: ABSENT_SHOWN, sleeping: ABSENT_SHOWN });

function loadLocal(key: string): boolean | null {
    try {
        const raw = readKey(key);
        return raw === '1' ? true : raw === '0' ? false : null;
    } catch {
        return null;
    }
}

function chosen(id: OptionalSection, cls: ViewClass): boolean | null {
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    const key = storageKey(id, cls);
    const value = bridge && typeof bridge.read === 'function'
        ? bridge.read(preferenceField(id, cls), () => loadLocal(key))
        : loadLocal(key);
    return typeof value === 'boolean' ? value : null;
}

function loadFor(id: OptionalSection, cls: ViewClass): boolean {
    const desktop = chosen(id, 'desktop');
    if (cls === 'mobile') return chosen(id, 'mobile') ?? desktop ?? ABSENT_SHOWN;
    return desktop ?? ABSENT_SHOWN;
}

export function sectionShown(id: OptionalSection): boolean {
    return view[id];
}

export function setSectionShown(id: OptionalSection, next: boolean): boolean {
    if (next === view[id]) return false;
    view[id] = next;
    const cls = viewClass();
    const writeLocal = (): void => {
        try {
            writeKey(storageKey(id, cls), next ? '1' : '0');
        } catch (err) {
            console.warn(`SessionSidebarSections: could not persist the ${id} toggle:`, err);
        }
    };
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    if (bridge && typeof bridge.write === 'function') {
        bridge.write(preferenceField(id, cls), next, writeLocal).catch((err: unknown) => {
            console.warn(`SessionSidebarSections: could not share the ${id} toggle:`, err);
        });
    } else {
        writeLocal();
    }
    void drawerController()?.refreshNow?.();
    return true;
}

export function init(): void {
    const cls = viewClass();
    for (const id of OPTIONAL_SECTIONS) {
        const next = loadFor(id, cls);
        if (next !== view[id]) view[id] = next;
    }
}
