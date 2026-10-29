/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import StatusLed from './StatusLed.svelte';
import { ASLEEP_UNREAD_LABEL, ledHtmlForStatus } from './status-dot';

let mounted: ReturnType<typeof mount> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

function light(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.appendChild(target);
    mounted = mount(StatusLed, { target, props });
    flushSync();
    const el = target.querySelector<HTMLElement>('.status-led');
    if (!el) throw new Error('StatusLed rendered no light');
    return el;
}

describe('an asleep session flagged for follow-up', () => {
    test('paints the unread moon and says why', () => {
        const el = light({ status: 'asleep', unread: true, size: '9px' });
        expect(el.dataset.inner).toBe('asleep-unread');
        expect(el.dataset.outer).toBe('off');
        expect(el.getAttribute('title')).toBe(ASLEEP_UNREAD_LABEL);
        expect(el.getAttribute('aria-label')).toBe(ASLEEP_UNREAD_LABEL);
        expect(el.classList.contains('status-dot--asleep')).toBe(true);
    });

    test('NEGATIVE CONTROL: unflagged is the plain grey moon with the plain words', () => {
        const el = light({ status: 'asleep', unread: false });
        expect(el.dataset.inner).toBe('asleep');
        expect(el.getAttribute('title')).not.toContain('flagged');
    });

    test('the component and the string renderer agree on both moons', () => {
        for (const unread of [true, false]) {
            const el = light({ status: 'asleep', unread });
            const html = ledHtmlForStatus('asleep', { unread });
            expect(html).toContain(`data-inner="${el.dataset.inner}"`);
            expect(html).toContain(`title="${el.getAttribute('title')}"`);
            unmount(mounted!);
            mounted = null;
        }
    });
});
