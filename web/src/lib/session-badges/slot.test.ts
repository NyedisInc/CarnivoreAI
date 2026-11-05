/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import BadgeSlot from './BadgeSlot.svelte';
import { badgeSlotPlan, registerBadgeSource, SLOT_MAX_ITEMS, type BadgeItem, type BadgeKind } from './slot';

const off: Array<() => void> = [];
afterEach(() => { off.splice(0).forEach((f) => f()); document.body.innerHTML = ''; });

const item = (kind: BadgeKind, n: number, extra: Partial<BadgeItem> = {}): BadgeItem => ({ kind, key: String(n), text: `${kind}${n}`, title: `${kind} ${n}`, ...extra });

describe('badge slot plan', () => {
    test('no source or no badges draws nothing', () => {
        expect(badgeSlotPlan({ name: 'a' })).toBeNull();
        off.push(registerBadgeSource('pr', () => []));
        expect(badgeSlotPlan({ name: 'a' })).toBeNull();
        expect(badgeSlotPlan(undefined)).toBeNull();
    });

    test('fixed order whatever the registration order, kind cap folds into +N', () => {
        off.push(registerBadgeSource('pr', () => [item('pr', 1)]));
        off.push(registerBadgeSource('ports', () => [1, 2, 3, 4].map((n) => item('ports', n)), 3));
        off.push(registerBadgeSource('progress', () => [item('progress', 1, { pct: 40 })]));
        const plan = badgeSlotPlan({})!;
        expect(plan.items.map((b) => b.text)).toEqual(['progress1', 'ports1', 'ports2', 'ports3', 'pr1']);
        expect(plan.more).toBe(1);
        expect(plan.moreTitle).toBe('ports 4');
    });

    test('the slot cap folds the tail, and a throwing source draws nothing', () => {
        off.push(registerBadgeSource('ports', () => Array.from({ length: 9 }, (_, i) => item('ports', i))));
        off.push(registerBadgeSource('pr', () => { throw new Error('boom'); }));
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const plan = badgeSlotPlan({})!;
        expect(plan.items).toHaveLength(SLOT_MAX_ITEMS);
        expect(plan.more).toBe(9 - SLOT_MAX_ITEMS);
        expect(warn).toHaveBeenCalledOnce();
        warn.mockRestore();
    });
});

describe('BadgeSlot', () => {
    test('a clickable badge is a button whose click stops at the badge; a mark is inert', () => {
        const act = vi.fn();
        off.push(registerBadgeSource('ports', () => [item('ports', 1, { activate: act }), item('ports', 2)]));
        const rowClick = vi.fn();
        const host = document.createElement('div');
        host.addEventListener('click', rowClick);
        document.body.appendChild(host);
        const c = mount(BadgeSlot, { target: host, props: { plan: badgeSlotPlan({}) } });
        flushSync();
        const btn = host.querySelector('button.row-badge') as HTMLButtonElement;
        expect(btn.textContent).toBe('ports1');
        btn.click();
        expect(act).toHaveBeenCalledOnce();
        expect(rowClick).not.toHaveBeenCalled();
        expect(host.querySelectorAll('span.row-badge[role="img"]')).toHaveLength(1);
        unmount(c);
    });
});
