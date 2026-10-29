/* there is nothing */

import { PreferenceField } from '../zone-shell/preference-field';
import { defaultFor, PREFERENCE_FIELD, type IconKind } from '../drawer/row-icon-prefs';

export type { IconKind };
export { PREFERENCE_FIELD as ROW_ICONS_FIELD };

export type RowDensity = 'compact' | 'cozy' | 'detailed';

export const ROW_DENSITIES: readonly RowDensity[] = ['compact', 'cozy', 'detailed'];

export const ROW_ICON_KINDS: readonly IconKind[] = ['agents', 'shells', 'timers', 'cup', 'pin', 'menu', 'context', 'automations'];

type SparseCell = Partial<Record<IconKind, boolean>>;

export type SparseRowIcons = Partial<Record<RowDensity, SparseCell | null>>;

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

    readonly #pref = new PreferenceField(PREFERENCE_FIELD, (value) => {
        this.value = sanitize(value);
    });

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        this.#pref.start(target);
    }

    reload(): void {
        this.#pref.reload();
    }

    effective(density: RowDensity, kind: IconKind): boolean {
        const stored = this.value[density]?.[kind];
        return typeof stored === 'boolean' ? stored : defaultFor(density, kind);
    }

    set(density: RowDensity, kind: IconKind, on: boolean): void {
        const next: SparseRowIcons = { ...this.value, [density]: { ...this.value[density], [kind]: on } };
        this.value = next;
        void this.#pref.write(next);
    }
}

export const rowIcons = new RowIconsStore();
