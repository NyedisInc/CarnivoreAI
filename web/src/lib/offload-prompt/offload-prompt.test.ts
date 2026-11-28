/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({ ...(await original<object>()), authFetch }));

import { ApiError } from '../../opscenter/api/auth.svelte';
import { runWake } from '../drawer/row-menu-sleep';
import { CANCELLED, canOfferRestore, runWithOffloadRestore } from './offload-prompt';

type Win = Record<string, any>;
const win = window as unknown as Win;
const WHEN = Date.UTC(2026, 9, 24, 12) / 1000;

let details: Record<string, unknown>;
let restoreAnswer: () => Promise<unknown>;
let wakes: unknown[][];

const until = async (probe: () => unknown): Promise<void> => {
    for (let i = 0; i < 50 && !probe(); i += 1) await new Promise((r) => setTimeout(r, 0));
    expect(probe()).toBeTruthy();
};
const q = (sel: string): HTMLElement | null => document.querySelector<HTMLElement>(sel);
const restoreCalls = (): unknown[][] => authFetch.mock.calls.filter((c) => String(c[0]).includes('/restore'));

function standUp(): void {
    wakes = [];
    let restored = false;
    authFetch.mockImplementation(async (path: string) => {
        if (path.startsWith('/offloaded')) return details;
        if (path.includes('/restore')) { const out = await restoreAnswer(); restored = true; return out; }
        throw new Error(`unexpected ${path}`);
    });
    win.SessionSidebar = { activeTmuxName: () => 'work_a', forceRefresh: async () => {} };
    win.Launchpad = { showError: () => {} };
    win.API = {
        wakeSession: async (...args: unknown[]) => {
            wakes.push(args);
            return restored ? { status: 'started', session_id: 's1' } : { status: 'refused', code: 'offloaded', detail: 'offloaded' };
        },
    };
}

beforeEach(() => {
    details = { conversations: ['c1', 'c2'], bytes: 1_572_864, offloaded_at: WHEN, plugin_on: true, unreadable: false };
    restoreAnswer = async () => ({ conversations: [{ conversation_id: 'c1', status: 'written' }, { conversation_id: 'c2', status: 'already_present' }] });
    authFetch.mockReset();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => {
    document.body.innerHTML = '';
    for (const k of ['API', 'Launchpad', 'SessionSidebar']) delete win[k];
    vi.restoreAllMocks();
});

describe('a wake refused offloaded', () => {
    it('shows the prompt with what is offloaded, its size and its date, and not an error or a start fresh', async () => {
        standUp();
        const run = runWake({ name: 'work_a', label: 'build', sessionUuid: 'S1' });
        await until(() => q('[data-offload-restore]'));
        expect(q('[data-offload-message]')!.textContent).toBe('2 conversations of "build" are in the backup vault, not on this computer.');
        expect(q('[data-offload-facts]')!.textContent).toBe('1.5 mb, offloaded 24 oct.');
        expect(q('[data-offload-restore]')!.getAttribute('data-btn')).toBe('confirm');
        expect(q('[data-offload-cancel]')!.getAttribute('data-btn')).toBe('secondary');
        expect(document.body.textContent).not.toMatch(/start fresh/i);
        q('[data-offload-cancel]')!.click();
        await run;
    });

    it('restore calls the restore route once, then the wake once more, and the wake starts', async () => {
        standUp();
        const run = runWake({ name: 'work_a', label: 'build', sessionUuid: 'S1' });
        await until(() => q('[data-offload-restore]'));
        expect(wakes).toHaveLength(1);
        q('[data-offload-restore]')!.click();
        expect(await run).toBe(true);
        expect(restoreCalls()).toEqual([['/cplugs/save/offload/sessions/S1/restore', { method: 'POST', body: '{}' }]]);
        expect(wakes).toHaveLength(2);
        expect(wakes.every((args) => args[3] !== true)).toBe(true);
        expect(q('.modal-overlay')).toBeNull();
    });

    it('cancel restores nothing and wakes nothing again', async () => {
        standUp();
        const run = runWake({ name: 'work_a', label: 'build', sessionUuid: 'S1' });
        await until(() => q('[data-offload-cancel]'));
        q('[data-offload-cancel]')!.click();
        expect(await run).toBe(false);
        expect(restoreCalls()).toEqual([]);
        expect(wakes).toHaveLength(1);
    });

    it('with backups off there is no restore button, it says to turn backups on, and a close wakes nothing', async () => {
        standUp();
        details = { ...details, plugin_on: false };
        const run = runWake({ name: 'work_a', label: 'build', sessionUuid: 'S1' });
        await until(() => q('[data-offload-cancel]'));
        expect(q('[data-offload-restore]')).toBeNull();
        expect(q('[data-offload-note]')!.textContent).toBe('turn backups on to restore.');
        expect(q('[data-offload-cancel]')!.textContent).toBe('close');
        expect(document.body.textContent).not.toMatch(/start fresh/i);
        q('[data-offload-cancel]')!.click();
        await run;
        expect(restoreCalls()).toEqual([]);
        expect(wakes).toHaveLength(1);
    });

    it('a restore that finds the conversation in another folder names that file, and does not run the wake again', async () => {
        standUp();
        restoreAnswer = async () => ({ conversations: [{ conversation_id: 'c1', status: 'present_elsewhere', path: '/p/-x/c1.jsonl' }] });
        const run = runWake({ name: 'work_a', label: 'build', sessionUuid: 'S1' });
        await until(() => q('[data-offload-restore]'));
        q('[data-offload-restore]')!.click();
        await until(() => q('[data-offload-failure]'));
        expect(q('[data-offload-failure]')!.textContent).toContain('already on disk at /p/-x/c1.jsonl');
        expect(wakes).toHaveLength(1);
        q('[data-offload-cancel]')!.click();
        await run;
    });

    it('a restore that finds a different copy on disk says so, keeps the prompt, and does not run the wake again', async () => {
        standUp();
        restoreAnswer = async () => ({ conversations: [{ conversation_id: 'c1', status: 'conflict' }] });
        const run = runWake({ name: 'work_a', label: 'build', sessionUuid: 'S1' });
        await until(() => q('[data-offload-restore]'));
        q('[data-offload-restore]')!.click();
        await until(() => q('[data-offload-failure]'));
        expect(q('[data-offload-failure]')!.textContent).toContain('a different copy');
        expect(q('[data-offload-restore]')).not.toBeNull();
        expect(wakes).toHaveLength(1);
        q('[data-offload-cancel]')!.click();
        await run;
    });
});

describe('runWithOffloadRestore', () => {
    const refusal = (): ApiError => new ApiError('offloaded', 409, 'offloaded', { detail: { code: 'offloaded' } });

    it('re-issues a rejected action exactly once after a restore, and a second refusal is not prompted again', async () => {
        authFetch.mockImplementation(async (path: string) => (path.startsWith('/offloaded') ? details : { conversations: [{ conversation_id: 'c1', status: 'written' }] }));
        const action = vi.fn(async () => { throw refusal(); });
        const run = runWithOffloadRestore({ sessionUuid: 'S1' }, action);
        const settled = run.catch((e) => e);
        await until(() => q('[data-offload-restore]'));
        q('[data-offload-restore]')!.click();
        expect(await settled).toBeInstanceOf(ApiError);
        expect(action).toHaveBeenCalledTimes(2);
        expect(document.querySelectorAll('[data-offload-restore]')).toHaveLength(0);
    });

    it('a decline answers CANCELLED and does not run the action again', async () => {
        authFetch.mockImplementation(async () => details);
        const action = vi.fn(async () => { throw refusal(); });
        const run = runWithOffloadRestore({ conversationId: 'c1' }, action);
        await until(() => q('[data-offload-cancel]'));
        q('[data-offload-cancel]')!.click();
        expect(await run).toBe(CANCELLED);
        expect(action).toHaveBeenCalledTimes(1);
    });

    it('any other failure passes straight through with no prompt', async () => {
        const action = vi.fn(async () => { throw new ApiError('gone', 404, 'not_found', null); });
        await expect(runWithOffloadRestore({ sessionUuid: 'S1' }, action)).rejects.toThrow('gone');
        expect(q('.modal-overlay')).toBeNull();
    });
});

describe('canOfferRestore (the legacy restart picker asks it before drawing its restore button)', () => {
    it('is true with backups on, false with backups off, an unreadable list, or nothing offloaded', async () => {
        standUp();
        expect(await canOfferRestore({ sessionUuid: 'S1' })).toBe(true);
        details = { ...details, plugin_on: false };
        expect(await canOfferRestore({ sessionUuid: 'S1' })).toBe(false);
        details = { ...details, plugin_on: true, unreadable: true };
        expect(await canOfferRestore({ sessionUuid: 'S1' })).toBe(false);
        authFetch.mockImplementation(async () => { throw new ApiError('nothing', 404, null, null); });
        expect(await canOfferRestore({ sessionUuid: 'S1' })).toBe(false);
        expect(restoreCalls()).toHaveLength(0);
    });
});
