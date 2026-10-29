/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import LocationPanel from './LocationPanel.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import { ApiError } from '../sdk';
import type { Fetcher, LocationView } from './location-api';

setLocale('en');

const VIEW: LocationView = {
    location: '',
    root: '/state/vault',
    available: true,
    error: '',
    refusals: [],
    warnings: [
        {
            code: 'same_disk_transcripts',
            message: 'same disk as your transcripts',
            field: 'vaultLocation',
            detail: '/state/vault is on the same disk as /home/.claude/projects, so these copies are lost together if the disk fails; choose another disk',
        },
    ],
};

interface Call {
    path: string;
    method: string;
    body: Record<string, unknown> | null;
}

function harness(refuse = '') {
    const state = { view: { ...VIEW }, revision: 3 };
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        if (call.method === 'PUT') {
            if (refuse) throw new ApiError(refuse, 422, 'settings_refused', { detail: { code: 'settings_refused', detail: refuse } });
            const value = String((call.body!.settings as Record<string, unknown>).vaultLocation);
            state.view = { ...state.view, location: value, root: value || '/state/vault' };
            return {
                revision: ++state.revision,
                settings_warnings: [
                    { code: 'vault_left_behind', message: 'the old vault holds the only copy of 1 conversation(s)', field: 'vaultLocation', detail: 'the vault folder left behind, /old/vault, is kept where it is and not read from the new location' },
                ],
            };
        }
        return path.endsWith('/location') ? state.view : { revision: state.revision };
    }) as unknown as Fetcher;
    return { fetcher, calls, state };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await tick();
    flushSync();
}

let target: HTMLElement;
let panel: Record<string, unknown> | null = null;
afterEach(() => {
    if (panel) unmount(panel);
    panel = null;
    target?.remove();
});

function render(fetcher: Fetcher): HTMLElement {
    target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(LocationPanel, { target, props: { fetcher } });
    return target;
}

describe('vault location panel', () => {
    test('shows the folder in force, that it can be used, and the same-disk advice', async () => {
        const el = render(harness().fetcher);
        await settle();
        expect(el.querySelector('[data-tm="location-root"]')?.textContent).toContain('/state/vault');
        expect(el.querySelector('[data-tm="location-ok"]')).not.toBeNull();
        expect(el.querySelector('[data-tm="location-warn"]')?.textContent).toContain('same disk as your transcripts');
        expect(el.querySelector('[data-tm="location-warn-detail"]')?.textContent).toContain('lost together if the disk fails');
    });

    test('a save goes through the plugin settings route with the revision, and its advice is shown', async () => {
        const { fetcher, calls } = harness();
        const el = render(fetcher);
        await settle();
        const field = el.querySelector<HTMLInputElement>('[data-tm="location-field"]')!;
        field.value = '/Volumes/ExampleDrive/vault';
        field.dispatchEvent(new Event('input'));
        flushSync();
        el.querySelector<HTMLButtonElement>('[data-tm="location-save"]')!.click();
        await settle();
        const put = calls.find((c) => c.method === 'PUT')!;
        expect(put.path).toBe('/cplugs/save');
        expect(put.body).toEqual({ revision: 3, settings: { vaultLocation: '/Volumes/ExampleDrive/vault' } });
        expect(el.querySelector('[data-tm="location-note"]')).not.toBeNull();
        const warn = el.querySelector('[data-tm="location-warn"]')?.textContent ?? '';
        expect(warn).toContain('only copy');
        expect(warn).toContain('not read from the new location');
    });

    test('a refused folder is shown in the problem line and nothing is reported saved', async () => {
        const el = render(harness('/x/Dropbox/vault is inside ~/Dropbox, a synced folder').fetcher);
        await settle();
        const field = el.querySelector<HTMLInputElement>('[data-tm="location-field"]')!;
        field.value = '/x/Dropbox/vault';
        field.dispatchEvent(new Event('input'));
        flushSync();
        el.querySelector<HTMLButtonElement>('[data-tm="location-save"]')!.click();
        await settle();
        expect(el.querySelector('[data-tm="location-problem"]')?.textContent).toContain('synced folder');
        expect(el.querySelector('[data-tm="location-note"]')).toBeNull();
    });
});
