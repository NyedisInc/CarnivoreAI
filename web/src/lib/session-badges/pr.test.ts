/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount } from 'svelte';

vi.mock('../browser/select-push.svelte', () => ({ openPage: async () => ({}) }));

import BadgeSlot from './BadgeSlot.svelte';
import { badgeSlotPlan } from './index';

afterEach(() => { document.body.innerHTML = ''; });

function draw(row: Record<string, unknown>): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    mount(BadgeSlot, { target: host, props: { plan: badgeSlotPlan(row) } });
    flushSync();
    return host;
}

describe('pr badge', () => {
    test('draws on a row with ports, says state, ci and threads, and opens the PR in the system browser', () => {
        const open = vi.spyOn(window, 'open').mockImplementation(() => null);
        const host = draw({ host_key: 'local', local_servers: [{ port: 5173, url: 'http://localhost:5173' }],
            pr: { number: 142, state: 'open', ci: 'red', unresolved: 2, url: 'https://github.com/me/app/pull/142' } });
        const kinds = [...host.querySelectorAll('[data-badge-kind]')].map((b) => b.getAttribute('data-badge-kind'));
        expect(kinds).toEqual(['pr']);
        const pr = host.querySelector('[data-badge-kind="pr"]') as HTMLElement;
        expect(pr.textContent).toContain('#142');
        expect(pr.getAttribute('data-tone')).toBe('bad');
        pr.click();
        expect(open).toHaveBeenCalledWith('https://github.com/me/app/pull/142', '_blank', 'noopener');
        open.mockRestore();
    });

    test('merged is calm, no gh account is one inert hint, and no pr draws nothing', () => {
        expect(draw({ pr: { number: 9, state: 'merged', url: 'https://github.com/me/app/pull/9' } })
            .querySelector('[data-badge-kind="pr"]')?.getAttribute('data-tone')).toBe('good');
        const hint = draw({ pr: { hint: 'connect_gh' } }).querySelector('[data-badge-kind="pr"]') as HTMLElement;
        expect(hint.tagName).toBe('SPAN');
        expect(draw({ pr: null }).querySelector('[data-badge-kind="pr"]')).toBeNull();
    });
});
