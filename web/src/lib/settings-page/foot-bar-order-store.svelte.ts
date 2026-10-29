
import { whenLegacyBootComplete } from '../legacy-boot';

export const FOOT_BAR_ORDER_FIELD = 'foot_bar_order';

export type FootBarOrderId = 'context' | 'window_5h' | 'window_7d';

export const FOOT_BAR_ORDER_DEFAULT: readonly FootBarOrderId[] = ['context', 'window_5h', 'window_7d'];

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
    follow(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

export function sanitize(value: unknown): FootBarOrderId[] {
    const kept: FootBarOrderId[] = [];
    if (Array.isArray(value)) {
        for (const entry of value) {
            const id = FOOT_BAR_ORDER_DEFAULT.find((known) => known === entry);
            if (id && !kept.includes(id)) kept.push(id);
        }
    }
    for (const id of FOOT_BAR_ORDER_DEFAULT) if (!kept.includes(id)) kept.push(id);
    return kept;
}

class FootBarOrderStore {
    value = $state<FootBarOrderId[]>([...FOOT_BAR_ORDER_DEFAULT]);

    #started = false;

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        if (this.#started) return;
        this.#started = true;
        this.reload();
        bridge()?.follow(FOOT_BAR_ORDER_FIELD, (value) => {
            this.value = sanitize(value);
        });
        whenLegacyBootComplete(target, () => this.reload());
    }

    reload(): void {
        this.value = sanitize(bridge()?.read(FOOT_BAR_ORDER_FIELD, () => null));
    }

    move(id: FootBarOrderId, direction: 'up' | 'down'): void {
        const at = this.value.indexOf(id);
        const to = direction === 'up' ? at - 1 : at + 1;
        if (at < 0 || to < 0 || to >= this.value.length) return;
        const next = [...this.value];
        [next[at], next[to]] = [next[to] as FootBarOrderId, next[at] as FootBarOrderId];
        this.value = next;
        const found = bridge();
        if (found) void found.write(FOOT_BAR_ORDER_FIELD, next, () => {});
    }
}

export const footBarOrder = new FootBarOrderStore();
