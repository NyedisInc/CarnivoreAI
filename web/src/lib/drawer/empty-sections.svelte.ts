import { drawerController } from './controller-ref';
import { readKey, writeKey } from './storage';
import { drawerEnv } from './env';

export const STORAGE_KEY = 'carnivore.session.sidebar.hide_empty_sections';
export const PREFERENCE_FIELD = 'sidebar_hide_empty_sections';

interface BridgeGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => boolean): unknown;
        write?(field: string, value: boolean, local: () => void): Promise<unknown>;
    };
}

const view = $state({ hide: false });

function loadLocal(): boolean {
    try {
        return readKey(STORAGE_KEY) === '1';
    } catch {
        return false;
    }
}

export function emptySectionsHidden(): boolean {
    return view.hide;
}

export function setEmptySectionsHidden(next: boolean): boolean {
    if (next === view.hide) return false;
    view.hide = next;
    const writeLocal = (): void => {
        try {
            writeKey(STORAGE_KEY, next ? '1' : '0');
        } catch (err) {
            console.warn('SessionSidebarEmptySections: could not persist the hide empty sections toggle:', err);
        }
    };
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    if (bridge && typeof bridge.write === 'function') {
        bridge.write(PREFERENCE_FIELD, next, writeLocal).catch((err: unknown) => {
            console.warn('SessionSidebarEmptySections: could not share the hide empty sections toggle:', err);
        });
    } else {
        writeLocal();
    }
    drawerController()?.repaint();
    return true;
}

export function init(): void {
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    const value = bridge && typeof bridge.read === 'function' ? bridge.read(PREFERENCE_FIELD, loadLocal) : loadLocal();
    const next = value === true;
    if (next !== view.hide) view.hide = next;
}
