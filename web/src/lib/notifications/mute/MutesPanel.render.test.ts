/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { Translate } from '../../sessions/types';
import MutesPanel from './MutesPanel.svelte';
import type { Fetcher } from './api';

const t: Translate = (key, params) => (params ? `${key}:${JSON.stringify(params)}` : key);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
        for (let j = 0; j < 8; j += 1) await Promise.resolve();
        await tick();
        flushSync();
    }
}

function server(body: unknown = { device: 'me', everywhere: ['session.finished'], here: [], devices: { phone: { label: 'phone', types: ['session.permission'] } } }) {
    const puts: Array<Record<string, unknown>> = [];
    const fetcher = (async (path: string, init?: { method?: string; body?: string }) => {
        if (path.startsWith('/notifications/types')) return { types: [{ id: 'session.finished', label_key: 'k.finished' }] };
        if (init?.method === 'PUT') { puts.push(JSON.parse(init.body ?? '{}')); return { device: 'me', everywhere: [], here: [], devices: {} }; }
        if (body === 'fail') throw new Error('down');
        return body;
    }) as unknown as Fetcher;
    return { fetcher, puts };
}

async function show(body?: unknown) {
    const s = server(body);
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(MutesPanel, { target, props: { t, fetcher: s.fetcher } });
    await settle();
    return { root: target, ...s };
}

describe('the muted notifications panel', () => {
    test('each mute is a base list row with its place and an unmute button', async () => {
        const { root } = await show();
        const rows = [...root.querySelectorAll('[data-mutes="list"].oc-list > .oc-list__row')];
        expect(rows).toHaveLength(2);
        expect(rows[0]!.getAttribute('data-mute-scope')).toBe('everywhere');
        expect(rows[0]!.querySelector('.oc-list__primary')?.textContent).toBe('k.finished');
        expect(rows[0]!.querySelector('.oc-list__meta')?.textContent).toBe('settings.notify.mutes.scope.everywhere');
        expect(rows[1]!.getAttribute('data-mute-scope')).toBe('here');
        expect(rows[1]!.querySelector('.oc-list__primary')?.textContent).toBe('session.permission');
        expect(rows[0]!.querySelector('.oc-list__actions button[data-btn]')).not.toBeNull();
    });

    test('unmute sends the PUT for that row only', async () => {
        const { root, puts } = await show();
        root.querySelector<HTMLButtonElement>('[data-mute-type="session.finished"] button')!.click();
        await settle();
        expect(puts).toEqual([{ type_id: 'session.finished', scope: 'everywhere', muted: false }]);
    });

    test('nothing muted says so in the base State, and a failed read is an alert', async () => {
        const empty = await show({ device: 'me', everywhere: [], here: [], devices: {} });
        expect(empty.root.querySelector('.oc-state[data-state="empty"]')?.textContent).toContain('settings.notify.mutes.empty');
        unmount(mounted!);
        mounted = null;
        document.body.innerHTML = '';
        const failed = await show('fail');
        expect(failed.root.querySelector('.oc-state[data-state="error"][role="alert"]')).not.toBeNull();
    });
});
