import { drawerController } from './controller-ref';
import { readKey, writeKey } from './storage';
import { drawerEnv } from './env';
import { viewClass, type ViewClass } from './view-class';

export const STORAGE_KEY = 'carnivore.session.sidebar.density';
export const MOBILE_STORAGE_KEY = 'carnivore.session.sidebar.density.mobile';
export const PREFERENCE_FIELD = 'sidebar_density';
export const MOBILE_PREFERENCE_FIELD = 'sidebar_density_mobile';
export const MODES: readonly string[] = ['compact', 'cozy', 'detailed'];
export const DEFAULT_MODE = 'compact';

interface BridgeGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => string | null): unknown;
        write?(field: string, value: string, local: () => void): Promise<unknown>;
    };
}

let mode = DEFAULT_MODE;

function loadLocalMode(): string {
    let raw: string | null = null;
    try {
        raw = readKey(STORAGE_KEY);
    } catch {
        console.warn('SessionSidebarDensity: storage unreadable, using default density');
        return DEFAULT_MODE;
    }
    if (raw === null || raw === undefined || raw === '') return DEFAULT_MODE;
    if (MODES.indexOf(raw) === -1) {
        console.warn(`SessionSidebarDensity: stored density ${JSON.stringify(raw)} is not a mode, using default`);
        return DEFAULT_MODE;
    }
    return raw;
}

function loadLocalMobileMode(): string | null {
    let raw: string | null = null;
    try {
        raw = readKey(MOBILE_STORAGE_KEY);
    } catch {
        return null;
    }
    return raw !== null && MODES.indexOf(raw) !== -1 ? raw : null;
}

function loadDesktopMode(): string {
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    if (bridge && typeof bridge.read === 'function') {
        const shared = bridge.read(PREFERENCE_FIELD, loadLocalMode);
        return typeof shared === 'string' && MODES.indexOf(shared) !== -1 ? shared : DEFAULT_MODE;
    }
    return loadLocalMode();
}

function ownMobileMode(): string | null {
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    const value = bridge && typeof bridge.read === 'function'
        ? bridge.read(MOBILE_PREFERENCE_FIELD, loadLocalMobileMode) : loadLocalMobileMode();
    return typeof value === 'string' && MODES.indexOf(value) !== -1 ? value : null;
}

function loadMode(cls: ViewClass): string {
    return cls === 'mobile' ? (ownMobileMode() || loadDesktopMode()) : loadDesktopMode();
}

export function currentMode(): string {
    return mode;
}

export function apply(): void {
    const panel = drawerController()?.panel;
    if (panel) panel.setAttribute('data-density', mode);
}

export function setMode(next: string): boolean {
    if (MODES.indexOf(next) === -1) return false;
    const cls = viewClass();
    if (next === (cls === 'mobile' ? ownMobileMode() : mode)) return false;
    mode = next;
    const field = cls === 'mobile' ? MOBILE_PREFERENCE_FIELD : PREFERENCE_FIELD;
    const writeLocal = (): void => {
        try {
            writeKey(cls === 'mobile' ? MOBILE_STORAGE_KEY : STORAGE_KEY, mode);
        } catch (err) {
            console.warn('SessionSidebarDensity: could not persist density:', err);
        }
    };
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    if (bridge && typeof bridge.write === 'function') {
        bridge.write(field, mode, writeLocal).catch((err: unknown) => {
            console.warn('SessionSidebarDensity: could not share density:', err);
        });
    } else {
        writeLocal();
    }
    apply();
    drawerController()?.repaint();
    return true;
}

export function init(): void {
    mode = loadMode(viewClass());
    apply();
}
