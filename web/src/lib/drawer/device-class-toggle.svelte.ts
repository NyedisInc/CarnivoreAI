import { readKey, writeKey } from './storage';
import { drawerEnv } from './env';
import { viewClass, type ViewClass } from './view-class';

interface BridgeGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => boolean | null): unknown;
        write?(field: string, value: boolean, local: () => void): Promise<unknown>;
    };
}

export interface DeviceClassToggleSpec<V extends boolean | null> {
    storageKey: string;
    mobileStorageKey: string;
    field: string;
    mobileField: string;
    absentShown: boolean;
    initial: V;
    logName: string;
    noun: string;
    afterChange?: () => void;
}

export interface DeviceClassToggle<V extends boolean | null> {
    value(): V;
    set(next: boolean): boolean;
    init(): void;
}

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

export function createDeviceClassToggle<V extends boolean | null>(spec: DeviceClassToggleSpec<V>): DeviceClassToggle<V> {
    const view = $state<{ shown: boolean | null }>({ shown: spec.initial });

    const loadFor = (cls: ViewClass): boolean => {
        const desktop = chosen(spec.field, spec.storageKey);
        if (cls === 'mobile') return chosen(spec.mobileField, spec.mobileStorageKey) ?? desktop ?? spec.absentShown;
        return desktop ?? spec.absentShown;
    };

    return {
        value: () => view.shown as V,
        set(next: boolean): boolean {
            if (next === view.shown) return false;
            view.shown = next;
            const mobile = viewClass() === 'mobile';
            const writeLocal = (): void => {
                try {
                    writeKey(mobile ? spec.mobileStorageKey : spec.storageKey, next ? '1' : '0');
                } catch (err) {
                    console.warn(`${spec.logName}: could not persist the ${spec.noun} toggle:`, err);
                }
            };
            const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
            if (bridge && typeof bridge.write === 'function') {
                bridge.write(mobile ? spec.mobileField : spec.field, next, writeLocal).catch((err: unknown) => {
                    console.warn(`${spec.logName}: could not share the ${spec.noun} toggle:`, err);
                });
            } else {
                writeLocal();
            }
            spec.afterChange?.();
            return true;
        },
        init(): void {
            const next = loadFor(viewClass());
            if (next !== view.shown) view.shown = next;
        },
    };
}
