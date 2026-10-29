
import { whenLegacyBootComplete } from '../legacy-boot';
import { defaultFor, PREFERENCE_FIELD, type IconKind } from '../drawer/row-icon-prefs';

export type { IconKind };
export { PREFERENCE_FIELD as ROW_ICONS_FIELD };

export type RowDensity = 'compact' | 'cozy' | 'detailed';

export const ROW_DENSITIES: readonly RowDensity[] = ['compact', 'cozy', 'detailed'];

export const ROW_ICON_KINDS: readonly IconKind[] = ['agents', 'shells', 'timers', 'cup', 'pin', 'menu', 'context', 'automations'];

type SparseCell = Partial<Record<IconKind, boolean>>;

export type SparseRowIcons = Partial<Record<RowDensity, SparseCell | null>>;

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
    follow(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
}

export function sanitize(value: unknown): SparseRowIcons {
    if (!isPlainObject(value)) return {};
    const result: SparseRowIcons = {};
    for (const density of ROW_DENSITIES) {
        const cell = value[density];
        if (!isPlainObject(cell)) continue;
        const kept: SparseCell = {};
        for (const kind of ROW_ICON_KINDS) {
            if (typeof cell[kind] === 'boolean') kept[kind] = cell[kind] as boolean;
        }
        if (Object.keys(kept).length > 0) result[density] = kept;
    }
    return result;
}

class RowIconsStore {
    value = $state<SparseRowIcons>({});

    #started = false;

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        if (this.#started) return;
        this.#started = true;
        this.reload();
        bridge()?.follow(PREFERENCE_FIELD, (value) => {
            this.value = sanitize(value);
        });
        whenLegacyBootComplete(target, () => this.reload());
    }

    reload(): void {
        this.value = sanitize(bridge()?.read(PREFERENCE_FIELD, () => null));
    }

    effective(density: RowDensity, kind: IconKind): boolean {
        const stored = this.value[density]?.[kind];
        return typeof stored === 'boolean' ? stored : defaultFor(density, kind);
    }

    set(density: RowDensity, kind: IconKind, on: boolean): void {
        const next: SparseRowIcons = { ...this.value, [density]: { ...this.value[density], [kind]: on } };
        this.value = next;
        const found = bridge();
        if (found) void found.write(PREFERENCE_FIELD, next, () => {});
    }
}

export const rowIcons = new RowIconsStore();
