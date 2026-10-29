
import { FOOT_BAR_ITEM_DEFAULTS } from '../foot-bar-item-defaults';
import { PreferenceField } from '../zone-shell/preference-field';

export const FOOT_BAR_ITEMS_FIELD = 'foot_bar_items';

export type FootBarItemKind = 'model' | 'effort' | 'context' | 'window_5h' | 'window_7d' | 'agents' | 'shells' | 'timers';

export const FOOT_BAR_ITEM_KINDS: readonly FootBarItemKind[] = [
    'model', 'effort', 'context', 'window_5h', 'window_7d', 'agents', 'shells', 'timers',
];

export type SparseFootBarItems = Partial<Record<FootBarItemKind, boolean>>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
}

export function sanitize(value: unknown): SparseFootBarItems {
    if (!isPlainObject(value)) return {};
    const kept: SparseFootBarItems = {};
    for (const kind of FOOT_BAR_ITEM_KINDS) {
        if (typeof value[kind] === 'boolean') kept[kind] = value[kind] as boolean;
    }
    return kept;
}

class FootBarItemsStore {
    value = $state<SparseFootBarItems>({});

    readonly #pref = new PreferenceField(FOOT_BAR_ITEMS_FIELD, (value) => {
        this.value = sanitize(value);
    });

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        this.#pref.start(target);
    }

    reload(): void {
        this.#pref.reload();
    }

    effective(kind: FootBarItemKind): boolean {
        const stored = this.value[kind];
        return typeof stored === 'boolean' ? stored : FOOT_BAR_ITEM_DEFAULTS[kind] ?? true;
    }

    set(kind: FootBarItemKind, on: boolean): void {
        const next: SparseFootBarItems = { ...this.value, [kind]: on };
        this.value = next;
        void this.#pref.write(next);
    }
}

export const footBarItems = new FootBarItemsStore();
