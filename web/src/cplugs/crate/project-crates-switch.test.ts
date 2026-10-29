/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

import { resourcePush } from '../sdk';
import { setLocale } from '../../lib/i18n/index.svelte';
import ProjectCrates from './ProjectCrates.svelte';

const BUNDLE_ID = 'crate-20261017T000000Z-project-1a2b3c4d';
const BUNDLE = {
    bundle_id: BUNDLE_ID, sha256: 'ab'.repeat(32), scope: 'project', label: null, created_at: '2026-10-17T00:00:00Z', verified_at: null,
    local_removed: false, conversations: 1, locations: [{ where: `/state/crates/${BUNDLE_ID}.crate`, verified_at: null, state: 'present' }],
};

vi.mock('../sdk', async (original) => ({
    ...(await original<Record<string, unknown>>()),
    authFetch: vi.fn(async (path: string) => (path.includes('/verify') ? { job_id: 'job-1' } : path.includes('/jobs/') ? { job_id: 'job-1', kind: 'verify', state: 'running' } : { bundles: [BUNDLE] })),
}));

setLocale('en');

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await new Promise((done) => setTimeout(done, 5));
        flushSync();
    }
}

let instance: Record<string, unknown> | null = null;
afterEach(() => {
    if (instance) unmount(instance);
    instance = null;
    document.body.innerHTML = '';
    resourcePush().store.closed();
});

test('switching to another project clears the running flag a verify set', async () => {
    const state = new SvelteMap<string, number>([['project', 7]]);
    const header = createRawSnippet(() => ({ render: () => '<div data-header></div>' }));
    const target = document.createElement('div');
    document.body.append(target);
    instance = mount(ProjectCrates, {
        target,
        props: { get projectId() { return state.get('project')!; }, header, isFolded: () => false, age: () => 'now', previewOf: (count: number) => count },
    } as never) as Record<string, unknown>;
    await settle();
    const verify = (): HTMLButtonElement => target.querySelector<HTMLButtonElement>(`[data-crt-verify="${BUNDLE_ID}"]`)!;
    verify().click();
    await settle();
    expect(verify().disabled).toBe(true);

    state.set('project', 8);
    await settle();
    expect(verify().disabled).toBe(false);
});
