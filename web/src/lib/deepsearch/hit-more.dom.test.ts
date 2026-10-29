/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const { default: HitRow } = await import('./HitRow.svelte');
const { DeepSearchController } = await import('./deepsearch.svelte');

const ORDER = ['read', 'go', 'branch', 'link', 'bookmark', 'scope', 'closest'];

let host: HTMLElement;
let mounted: Record<string, unknown> | null = null;
beforeEach(() => { host = document.createElement('div'); document.body.append(host); });
afterEach(() => { if (mounted) unmount(mounted); mounted = null; host.remove(); document.body.replaceChildren(); });

function paint(layout: 'ledger' | 'best'): void {
    const controller = new DeepSearchController({ search: async () => ({}) as never }, async () => 'switched', 'deepsearch.no_matches', () => {});
    controller.showActions = true;
    controller.layout = layout;
    const group = { sessionUuid: 's-1', conversationId: 'c-1', hostKey: null } as never;
    const hit = { line: 3, entryUuid: 'u-3', kind: 'user', snippet: 'a \u0002flux\u0003', fileKind: 'conversation', bookmark: { id: 9 } } as never;
    mounted = mount(HitRow, { target: host, props: { controller, group, hit, conv: 'live', name: 'nightly', id: 'h0', picked: false, meta: 'you, now', onopen: () => {}, tags: false } });
    flushSync();
}

const nodes = (): (string | null)[] => [...document.querySelectorAll('[role="menu"] [data-node]')].map((n) => n.getAttribute('data-node'));

for (const layout of ['ledger', 'best'] as const) {
    test(`a ${layout} hit draws the more button and its dropdown in the mock order`, async () => {
        paint(layout);
        const button = host.querySelector<HTMLElement>('[data-action="more"]');
        expect(button, 'the more button').not.toBeNull();
        expect(button!.getAttribute('data-size')).toBe('icon');
        button!.click();
        flushSync();
        await Promise.resolve();
        expect(nodes()).toEqual(ORDER);
    });
}

test('the hit\'s right click opens the same list', () => {
    paint('best');
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 10 });
    host.querySelector('.sd-hit')!.dispatchEvent(event);
    flushSync();
    expect(event.defaultPrevented).toBe(true);
    expect(nodes()).toEqual(ORDER);
});
