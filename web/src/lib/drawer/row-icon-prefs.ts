import { drawerController } from './controller-ref';
import { drawerEnv } from './env';

export const PREFERENCE_FIELD = 'drawer_row_icons';

export type IconKind = 'agents' | 'shells' | 'timers' | 'cup' | 'pin' | 'menu' | 'context' | 'automations';

export const DEFAULTS: Record<string, boolean> = { compact: false, cozy: true, detailed: true };

const EXTRA_KINDS: readonly IconKind[] = ['cup', 'pin', 'menu'];

const EXTRA_DEFAULT = true;

const CONTEXT_GAUGE_DEFAULT = true;

const AUTOMATIONS_DEFAULT = true;

export function defaultFor(density: string, icon: IconKind): boolean {
    if (icon === 'context') return CONTEXT_GAUGE_DEFAULT;
    if (icon === 'automations') return AUTOMATIONS_DEFAULT;
    if (EXTRA_KINDS.includes(icon)) return EXTRA_DEFAULT;
    return Object.prototype.hasOwnProperty.call(DEFAULTS, density) ? (DEFAULTS[density] ?? true) : true;
}

interface BridgeGlobals {
    PreferenceBridge?: {
        read?(field: string, fallback: () => unknown): unknown;
        follow?(field: string, apply: (value: unknown) => void): () => void;
    };
}

function bridge(): BridgeGlobals['PreferenceBridge'] {
    return (drawerEnv() as BridgeGlobals).PreferenceBridge;
}

type StoredSet = Partial<Record<IconKind, boolean>>;
type StoredBlock = Partial<Record<'compact' | 'cozy' | 'detailed', StoredSet | null>>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
}

function readBlock(): StoredBlock | null {
    const b = bridge();
    if (!b || typeof b.read !== 'function') return null;
    const value = b.read(PREFERENCE_FIELD, () => null);
    return isPlainObject(value) ? (value as StoredBlock) : null;
}

export function iconVisible(density: string, icon: IconKind): boolean {
    const fallback = defaultFor(density, icon);
    const set = readBlock()?.[density as 'compact' | 'cozy' | 'detailed'];
    if (!isPlainObject(set)) return fallback;
    const value = (set as StoredSet)[icon];
    return typeof value === 'boolean' ? value : fallback;
}

const DENSITY_KEYS = ['compact', 'cozy', 'detailed'] as const;

export function anyDensityShows(icon: IconKind): boolean {
    return DENSITY_KEYS.some((density) => iconVisible(density, icon));
}

const listeners = new Set<() => void>();

export function onIconPrefsChange(fn: () => void): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
}

let stopFollow: (() => void) | null = null;

export function init(): void {
    if (stopFollow) return;
    const b = bridge();
    if (!b || typeof b.follow !== 'function') return;
    stopFollow = b.follow(PREFERENCE_FIELD, () => {
        for (const fn of listeners) fn();
        drawerController()?.repaint();
    });
    for (const fn of listeners) fn();
}

export function _resetForTest(): void {
    stopFollow?.();
    stopFollow = null;
}
