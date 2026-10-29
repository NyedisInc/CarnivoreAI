/*  hidden  */
import { drawerController } from './controller-ref';
import { readKey, writeKey } from './storage';
import { drawerEnv } from './env';

export const STORAGE_KEY = 'carnivore.session.sidebar.leaders';
export const PREFERENCE_FIELD = 'sidebar_show_leaders';
export const PANEL_ATTR = 'data-leaders';

interface BridgeGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => boolean): unknown;
        write?(field: string, value: boolean, local: () => void): Promise<unknown>;
    };
}

let shown = true;

function loadLocal(): boolean {
    try {
        return readKey(STORAGE_KEY) !== '0';
    } catch {
        return true;
    }
}

export function leadersShown(): boolean {
    return shown;
}

export function apply(): void {
    drawerController()?.panel?.setAttribute(PANEL_ATTR, shown ? 'shown' : 'hidden');
}

export function setLeadersShown(next: boolean): boolean {
    if (next === shown) return false;
    shown = next;
    const writeLocal = (): void => {
        try {
            writeKey(STORAGE_KEY, shown ? '1' : '0');
        } catch (err) {
            console.warn('SessionSidebarLeaders: could not persist the leaders toggle:', err);
        }
    };
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    if (bridge && typeof bridge.write === 'function') {
        bridge.write(PREFERENCE_FIELD, shown, writeLocal).catch((err: unknown) => {
            console.warn('SessionSidebarLeaders: could not share the leaders toggle:', err);
        });
    } else {
        writeLocal();
    }
    apply();
    drawerController()?.repaint();
    return true;
}

export function init(): void {
    const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
    const value = bridge && typeof bridge.read === 'function' ? bridge.read(PREFERENCE_FIELD, loadLocal) : loadLocal();
    shown = value !== false;
    apply();
}
