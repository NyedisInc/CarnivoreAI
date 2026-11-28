/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({ ...(await original<object>()), authFetch }));

import { promptRestore, runWithOffloadRestore } from './offload-prompt';

const q = (sel: string): HTMLElement | null => document.querySelector<HTMLElement>(sel);
const until = async (probe: () => unknown): Promise<void> => {
    for (let i = 0; i < 50 && !probe(); i += 1) await new Promise((r) => setTimeout(r, 0));
    expect(probe()).toBeTruthy();
};

beforeEach(() => {
    authFetch.mockReset();
    authFetch.mockImplementation(async () => ({ conversations: ['c1'], bytes: 1024, offloaded_at: 1_700_000_000, plugin_on: true, unreadable: false }));
});
afterEach(() => { document.body.innerHTML = ''; });

it('a plain restore says it restores the conversation and promises nothing after', async () => {
    const run = promptRestore({ conversationId: 'c1', label: 'build' });
    await until(() => q('[data-offload-note]'));
    expect(q('[data-offload-note]')!.textContent).not.toContain('carries on');
    expect(q('[data-offload-note]')!.textContent).toContain('restoring copies the conversation back');
    q('[data-offload-cancel]')!.click();
    await run;
});

it('a restore that re-runs the refused action says it carries on with what was asked', async () => {
    const run = runWithOffloadRestore({ sessionUuid: 'S1', label: 'build' }, async () => ({ status: 'refused', code: 'offloaded' }));
    await until(() => q('[data-offload-note]'));
    expect(q('[data-offload-note]')!.textContent).toContain('carries on with what you asked');
    q('[data-offload-cancel]')!.click();
    await run;
});
