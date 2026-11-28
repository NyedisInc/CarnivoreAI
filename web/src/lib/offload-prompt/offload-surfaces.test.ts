/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({ ...(await original<object>()), authFetch }));

import { ApiError } from '../../opscenter/api/auth.svelte';
import type { HistorySession } from '../projects-shared/history-api';
import { diskTag, primaryAction } from '../projects-shared/ledger-model';
import { restartRecentSession } from '../launchpad/recent-actions';
import { rowAction } from '../sessions-page/row-action';
import { resumeWhyKey } from '../sessions-page/resume-why';
import { CANCELLED, runWithOffloadRestore } from './offload-prompt';

const q = (sel: string): HTMLElement | null => document.querySelector<HTMLElement>(sel);
const until = async (probe: () => unknown): Promise<void> => {
    for (let i = 0; i < 50 && !probe(); i += 1) await new Promise((r) => setTimeout(r, 0));
    expect(probe()).toBeTruthy();
};
const session = (extra: Partial<HistorySession>): HistorySession => ({
    session_uuid: 'S1', state: 'closed', host_key: 'local', claude_session_uuid: 'c1', has_transcript: false, ...extra,
} as HistorySession);

beforeEach(() => {
    authFetch.mockReset();
    authFetch.mockImplementation(async (path: string) => (path.startsWith('/offloaded')
        ? { conversations: ['c1'], bytes: 2048, offloaded_at: 1_762_000_000, plugin_on: true, unreadable: false }
        : { conversations: [{ conversation_id: 'c1', status: 'written' }] }));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('a history row flagged offloaded', () => {
    it('leads with restore (not disabled, not start, not gone) and says why, while a plainly gone row stays disabled', () => {
        const off = session({ offloaded: true });
        expect(primaryAction(off)).toEqual({ id: 'resume' });
        expect(rowAction(off)).toBe('restore');
        expect(diskTag(off)).toBe('offloaded');
        expect(resumeWhyKey(off)).toBe('projects.page.resume.why_offloaded');
        const gone = session({});
        expect(primaryAction(gone).id).toBe('none');
        expect(rowAction(gone)).toBeNull();
        expect(diskTag(gone)).toBe('gone');
    });

    it('an asleep offloaded row wakes (the wake restores first); it is never offered start fresh', () => {
        expect(rowAction(session({ state: 'asleep', offloaded: true }))).toBe('wake');
        expect(rowAction(session({ state: 'asleep' }))).toBe('start');
    });

    it('its resume opens the prompt, restores, then restarts exactly once more', async () => {
        const restart = vi.fn()
            .mockRejectedValueOnce(new ApiError('offloaded', 409, 'offloaded', { detail: { code: 'offloaded' } }))
            .mockResolvedValue({ ok: true, session: { id: 's' } });
        const host = { restart, showError: vi.fn(), refreshRunningSessions: async () => {}, refreshRecent: async () => {}, toast: vi.fn() };
        const run = restartRecentSession({ sessionUuid: 'S9', title: 'build', workingDir: '/w', agentType: '' }, host as never, (k: string) => k);
        await until(() => q('[data-offload-restore]'));
        expect(restart).toHaveBeenCalledTimes(1);
        q('[data-offload-restore]')!.click();
        await run;
        expect(restart).toHaveBeenCalledTimes(2);
        expect(authFetch.mock.calls.filter((c) => String(c[0]).includes('/restore')).map((c) => c[0])).toEqual(['/cplugs/save/offload/sessions/S9/restore']);
    });
});

describe('a respawn by tmux name refused offloaded', () => {
    const refused = (uuid: string | null) => ({ ok: false, kind: 'offloaded', code: 'offloaded', session_uuid: uuid, detail: 'offloaded' });

    it('opens the prompt on the session_uuid the server resolved, restores, and re-issues once', async () => {
        const issue = vi.fn().mockResolvedValueOnce(refused('S7')).mockResolvedValue({ ok: true });
        const run = runWithOffloadRestore({ sessionUuid: null, label: 'build' }, issue);
        await until(() => q('[data-offload-restore]'));
        q('[data-offload-restore]')!.click();
        expect(await run).toEqual({ ok: true });
        expect(issue).toHaveBeenCalledTimes(2);
        expect(authFetch.mock.calls.some((c) => c[0] === '/cplugs/save/offload/sessions/S7/restore')).toBe(true);
    });

    it('with no session_uuid anywhere keeps the plain sentence: no prompt, the refusal comes back as it is', async () => {
        const issue = vi.fn().mockResolvedValue(refused(null));
        expect(await runWithOffloadRestore({ sessionUuid: null }, issue)).toEqual(refused(null));
        expect(issue).toHaveBeenCalledTimes(1);
        expect(q('.modal-overlay')).toBeNull();
    });

    it('a decline answers CANCELLED', async () => {
        const issue = vi.fn().mockResolvedValue(refused('S7'));
        const run = runWithOffloadRestore({}, issue);
        await until(() => q('[data-offload-cancel]'));
        q('[data-offload-cancel]')!.click();
        expect(await run).toBe(CANCELLED);
        expect(issue).toHaveBeenCalledTimes(1);
    });
});
