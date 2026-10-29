import { describe, expect, it, vi } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { rowMenuNodes } from './row-menu-nodes';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

describe('rowMenuNodes', () => {
    it('always returns the three nodes, withdraw last, set apart and danger', () => {
        for (const state of [{ canCheck: true, canWithdraw: true }, { canCheck: false, canWithdraw: false }]) {
            const nodes = rowMenuNodes(state, t, vi.fn());
            expect(nodes.map((n) => n.id)).toEqual(['open', 'check', 'withdraw']);
            expect(nodes[2]?.sep).toBe(true);
            expect(nodes[2]?.danger).toBe(true);
        }
    });

    it('blocks check while a submission moves and withdraw when it is not withdrawable', () => {
        const [open, check, withdraw] = rowMenuNodes({ canCheck: false, canWithdraw: false }, t, vi.fn());
        expect(open?.blocked).toBeUndefined();
        expect(check?.blocked).toBe('waiting on a review');
        expect(withdraw?.blocked).toBe('not open to withdraw');
        const free = rowMenuNodes({ canCheck: true, canWithdraw: true }, t, vi.fn());
        expect(free.every((n) => n.blocked === undefined)).toBe(true);
    });

    it('a pick reports its action', () => {
        const pick = vi.fn();
        rowMenuNodes({ canCheck: true, canWithdraw: true }, t, pick)[1]?.run?.();
        expect(pick).toHaveBeenCalledWith('check');
    });
});
