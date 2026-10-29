
import { FOOT_BAR_ITEM_DEFAULTS } from '../foot-bar-item-defaults';
import { whenLegacyBootComplete } from '../legacy-boot';

export const FOOT_BAR_ITEMS_FIELD = 'foot_bar_items';

export type FootBarItemKind = 'model' | 'effort' | 'context' | 'window_5h' | 'window_7d' | 'agents' | 'shells' | 'timers';

export const FOOT_BAR_ITEM_KINDS: readonly FootBarItemKind[] = [
    'model', 'effort', 'context', 'window_5h', 'window_7d', 'agents', 'shells', 'timers',
];

export type SparseFootBarItems = Partial<Record<FootBarItemKind, boolean>>;

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

    #started = false;

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        if (this.#started) return;
        this.#started = true;
        this.reload();
        bridge()?.follow(FOOT_BAR_ITEMS_FIELD, (value) => {
            this.value = sanitize(value);
        });
        whenLegacyBootComplete(target, () => this.reload());
    }

    reload(): void {
        this.value = sanitize(bridge()?.read(FOOT_BAR_ITEMS_FIELD, () => null));
    }

    effective(kind: FootBarItemKind): boolean {
        const stored = this.value[kind];
        return typeof stored === 'boolean' ? stored : FOOT_BAR_ITEM_DEFAULTS[kind] ?? true;
    }

    set(kind: FootBarItemKind, on: boolean): void {
        const next: SparseFootBarItems = { ...this.value, [kind]: on };
        this.value = next;
        const found = bridge();
        if (found) void found.write(FOOT_BAR_ITEMS_FIELD, next, () => {});
    }
}

export const footBarItems = new FootBarItemsStore();
