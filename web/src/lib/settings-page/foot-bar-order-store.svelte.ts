
import { PreferenceField } from '../zone-shell/preference-field';

export const FOOT_BAR_ORDER_FIELD = 'foot_bar_order';

export type FootBarOrderId = 'context' | 'window_5h' | 'window_7d';

export const FOOT_BAR_ORDER_DEFAULT: readonly FootBarOrderId[] = ['context', 'window_5h', 'window_7d'];

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

    readonly #pref = new PreferenceField(FOOT_BAR_ORDER_FIELD, (value) => {
        this.value = sanitize(value);
    });

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        this.#pref.start(target);
    }

    reload(): void {
        this.#pref.reload();
    }

    move(id: FootBarOrderId, direction: 'up' | 'down'): void {
        const at = this.value.indexOf(id);
        const to = direction === 'up' ? at - 1 : at + 1;
        if (at < 0 || to < 0 || to >= this.value.length) return;
        const next = [...this.value];
        [next[at], next[to]] = [next[to] as FootBarOrderId, next[at] as FootBarOrderId];
        this.value = next;
        void this.#pref.write(next);
    }
}

export const footBarOrder = new FootBarOrderStore();
