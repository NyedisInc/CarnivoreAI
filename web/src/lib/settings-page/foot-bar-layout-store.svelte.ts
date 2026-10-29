
import { whenLegacyBootComplete } from '../legacy-boot';

export const FOOT_BAR_LAYOUT_FIELD = 'foot_bar_layout';

export type FootBarLayoutOption = 'a' | 'b' | 'c';

export const FOOT_BAR_LAYOUT_OPTIONS: readonly FootBarLayoutOption[] = ['a', 'b', 'c'];

export const FOOT_BAR_LAYOUT_DEFAULT: FootBarLayoutOption = 'a';

export interface SparseFootBarLayout {
    collapsed?: FootBarLayoutOption;
    open?: FootBarLayoutOption;
}

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

    #started = false;

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        if (this.#started) return;
        this.#started = true;
        this.reload();
        bridge()?.follow(FOOT_BAR_LAYOUT_FIELD, (value) => {
            this.value = sanitize(value);
        });
        whenLegacyBootComplete(target, () => this.reload());
    }

    reload(): void {
        this.value = sanitize(bridge()?.read(FOOT_BAR_LAYOUT_FIELD, () => null));
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
        const found = bridge();
        if (found) void found.write(FOOT_BAR_LAYOUT_FIELD, next, () => {});
    }
}

export const footBarLayout = new FootBarLayoutStore();
