
import { PreferenceField } from '../zone-shell/preference-field';

export const FOOT_BAR_LAYOUT_FIELD = 'foot_bar_layout';

export type FootBarLayoutOption = 'a' | 'b' | 'c';

export const FOOT_BAR_LAYOUT_OPTIONS: readonly FootBarLayoutOption[] = ['a', 'b', 'c'];

export const FOOT_BAR_LAYOUT_DEFAULT: FootBarLayoutOption = 'a';

export interface SparseFootBarLayout {
    collapsed?: FootBarLayoutOption;
    open?: FootBarLayoutOption;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
}

function isOption(value: unknown): value is FootBarLayoutOption {
    return typeof value === 'string' && (FOOT_BAR_LAYOUT_OPTIONS as readonly string[]).includes(value);
}

export function sanitize(value: unknown): SparseFootBarLayout {
    if (!isPlainObject(value)) return {};
    const kept: SparseFootBarLayout = {};
    if (isOption(value.collapsed)) kept.collapsed = value.collapsed;
    if (isOption(value.open)) kept.open = value.open;
    return kept;
}

class FootBarLayoutStore {
    value = $state<SparseFootBarLayout>({});

    readonly #pref = new PreferenceField(FOOT_BAR_LAYOUT_FIELD, (value) => {
        this.value = sanitize(value);
    });

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        this.#pref.start(target);
    }

    reload(): void {
        this.#pref.reload();
    }

    effective(half: 'collapsed' | 'open'): FootBarLayoutOption {
        const stored = this.value[half];
        return stored ?? FOOT_BAR_LAYOUT_DEFAULT;
    }

    set(half: 'collapsed' | 'open', option: FootBarLayoutOption): void {
        const next: Required<SparseFootBarLayout> = {
            collapsed: this.effective('collapsed'),
            open: this.effective('open'),
            [half]: option,
        };
        this.value = next;
        void this.#pref.write(next);
    }
}

export const footBarLayout = new FootBarLayoutStore();
