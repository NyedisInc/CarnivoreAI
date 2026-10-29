/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    offerFresh, pickAndWake, releaseThisTab, runArchive, runKillAsleep, runReopen, runSleep, runWake,
} from './row-menu-sleep';

type Win = Record<string, any>;
const win = window as unknown as Win;

let calls: unknown[][];
let said: string[];
let events: { type: string; detail?: unknown }[];
let refreshes: number;

function standUp(api: Win = {}, extra: Win = {}): void {
    calls = []; said = []; events = []; refreshes = 0;
    win.CloudeI18n = { t: (k: string, p?: unknown) => k + (p ? JSON.stringify(p) : '') };
    win.Launchpad = { showError: (text: string) => said.push(text) };
    win.SessionSidebar = { activeTmuxName: () => 'carnivore_a', forceRefresh: async () => { refreshes += 1; } };
    win.API = api;
    Object.assign(win, extra);
    window.addEventListener('cloude:primary-session-gone', onGone);
}

function onGone(e: Event): void { events.push({ type: e.type, detail: (e as CustomEvent).detail }); }

afterEach(() => {
    window.removeEventListener('cloude:primary-session-gone', onGone);
    for (const k of ['API', 'App', 'Launchpad', 'SessionSidebar', 'SessionRestartPicker', 'TerminalController', 'NavigationGeneration', 'WakeFocus', 'CloudeI18n']) delete win[k];
    vi.restoreAllMocks();
});
beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}));

const CTX = { name: 'carnivore_a', sessionUuid: 'u-a' };

describe('runSleep', () => {
    it('sends the uuid, and a refusal shows the server sentence and leaves this tab alone', async () => {
        const tc = { sessionActive: true, ws: { close: vi.fn() } };
        standUp({ sleepSession: async (u: string) => { calls.push(['sleep', u]); return { status: 'refused', detail: 'cannot sleep: no conversation id' }; } }, { TerminalController: tc });
        await runSleep(CTX);
        expect(calls).toEqual([['sleep', 'u-a']]);
        expect(said).toHaveLength(1);
        expect(said[0]).toContain('cannot sleep: no conversation id');
        expect(tc.sessionActive).toBe(true);
        expect(events).toEqual([]);
        expect(refreshes).toBe(1);
    });

    it('sleeping the session this tab shows releases the tab without reconnecting, and names the session that went', async () => {
        const close = vi.fn();
        const tc: Win = { sessionActive: true, stopReconnecting: vi.fn(), ws: { close } };
        standUp({ sleepSession: async () => ({ status: 'asleep' }) }, { TerminalController: tc });
        await runSleep(CTX);
        expect(said).toEqual([]);
        expect(tc.sessionActive).toBe(false);
        expect(tc._intentionalClose).toBe(true);
        expect(tc.stopReconnecting).toHaveBeenCalled();
        expect(close).toHaveBeenCalled();
        expect(tc.ws).toBeNull();
        expect(events).toEqual([{ type: 'cloude:primary-session-gone', detail: { tmuxName: 'carnivore_a' } }]);
    });

    it('releases nothing when another session is the one on screen', () => {
        standUp({}, { TerminalController: { sessionActive: true, ws: null } });
        win.SessionSidebar.activeTmuxName = () => 'carnivore_other';
        releaseThisTab({ name: 'carnivore_a' });
        expect(win.TerminalController.sessionActive).toBe(true);
        expect(events).toEqual([]);
    });

    it('says so, and calls nothing, with no session uuid', async () => {
        standUp({ sleepSession: async () => { calls.push(['sleep']); return { status: 'asleep' }; } });
        await runSleep({ name: 'carnivore_a' });
        expect(calls).toEqual([]);
        expect(said[0]).toContain('session.sleep.no_uuid');
    });
});

describe('runWake', () => {
    it('sends the uuid, stays quiet when it started, and hands the woken session to WakeFocus', async () => {
        const focus: unknown[][] = [];
        standUp({ wakeSession: async (u: string) => { calls.push(['wake', u]); return { status: 'started' }; } },
            { NavigationGeneration: { begin: () => 7 }, WakeFocus: { afterWake: (u: string, n: unknown) => focus.push([u, n]) } });
        expect(await runWake(CTX)).toBe(true);
        expect(calls).toEqual([['wake', 'u-a']]);
        expect(said).toEqual([]);
        expect(focus).toEqual([['u-a', 7]]);
    });

    it('a refused wake is false, says why, and focuses nothing', async () => {
        const focus: unknown[][] = [];
        standUp({ wakeSession: async () => ({ status: 'refused', detail: 'its transcript is gone' }) },
            { WakeFocus: { afterWake: (...a: unknown[]) => focus.push(a) } });
        expect(await runWake(CTX)).toBe(false);
        expect(said[0]).toContain('its transcript is gone');
        expect(focus).toEqual([]);
    });

    describe('wrapper_needed (#714)', () => {
        function pickerPage(pick: unknown, lastError = ''): unknown[][] {
            const opened: unknown[][] = [];
            standUp({
                wakeSession: async (u: string, agent?: string) => {
                    calls.push(['wake', u, agent]);
                    return agent ? { status: 'started' } : { status: 'refused', code: 'wrapper_needed', detail: 'not a configured launch wrapper' };
                },
            }, { SessionRestartPicker: { open: async (...a: unknown[]) => { opened.push(a); return pick; }, lastError: () => lastError } });
            return opened;
        }

        it('opens the restart picker with the uuid and wakes again with the pick', async () => {
            const opened = pickerPage({ agentType: 'claude-skip-permissions' });
            expect(await runWake({ name: 'carnivore_3D Work-2', label: '3D Work', sessionUuid: 'u-3d' })).toBe(true);
            expect(opened).toEqual([['carnivore_3D Work-2', '3D Work', null, 'u-3d']]);
            expect(calls).toEqual([['wake', 'u-3d', undefined], ['wake', 'u-3d', 'claude-skip-permissions']]);
            expect(said).toEqual([]);
        });

        it('cancelling the picker wakes nothing and says nothing', async () => {
            pickerPage(null);
            expect(await runWake(CTX)).toBe(false);
            expect(calls).toHaveLength(1);
            expect(said).toEqual([]);
            expect(refreshes).toBe(1);
        });

        it('a picker that could not load says why instead of going quiet', async () => {
            pickerPage(null, 'preview failed: 503');
            await runWake(CTX);
            expect(said).toHaveLength(1);
            expect(said[0]).toContain('preview failed: 503');
        });

        it('the account the picker returned reaches the wake call (#1641)', async () => {
            const seen: unknown[][] = [];
            standUp({ wakeSession: async (...a: unknown[]) => { seen.push(a); return { status: 'started' }; } },
                { SessionRestartPicker: { open: async () => ({ agentType: 'cld', account: { accountId: 'play', pinned: true } }) } });
            await pickAndWake('carnivore_a', 'a', 'u-a');
            expect(seen).toEqual([['u-a', 'cld', { accountId: 'play', pinned: true }]]);
        });

        it('with no picker on the page the refusal is shown as it is', async () => {
            standUp({ wakeSession: async () => ({ status: 'refused', code: 'wrapper_needed', detail: 'needs a wrapper' }) });
            expect(await runWake(CTX)).toBe(false);
            expect(said[0]).toContain('needs a wrapper');
        });
    });

    describe('transcript_missing (#2515)', () => {
        it('a yes starts a fresh conversation through the same route', async () => {
            const confirm = vi.fn(async () => true);
            standUp({
                wakeSession: async (...a: unknown[]) => { calls.push(['wake', ...a]); return a[3] ? { status: 'started' } : { status: 'refused', code: 'transcript_missing' }; },
            }, { App: { showConfirmModal: confirm } });
            expect(await runWake({ ...CTX, label: 'a' })).toBe(true);
            expect(calls[1]).toEqual(['wake', 'u-a', null, null, true]);
            expect(confirm).toHaveBeenCalledTimes(1);
        });

        it('a no wakes nothing more and shows the refusal', async () => {
            standUp({ wakeSession: async () => ({ status: 'refused', code: 'transcript_missing', detail: 'no transcript' }) },
                { App: { showConfirmModal: async () => false } });
            expect(await runWake(CTX)).toBe(false);
            expect(said[0]).toContain('no transcript');
            standUp({}, { App: { showConfirmModal: async () => false } });
            expect(await offerFresh('carnivore_a', 'a', 'u-a')).toBeNull();
        });
    });
});

describe('runKillAsleep', () => {
    const asleepCtx = { name: 'carnivore_a', label: 'agent a', sessionUuid: 'u-1' };
    it('confirms (danger styled, naming the agent), then deletes, then re-reads the list', async () => {
        const confirm = vi.fn(async (..._a: unknown[]) => true);
        standUp({ killAsleepSession: async (u: string) => { calls.push(['kill', u]); } }, { App: { showConfirmModal: confirm } });
        expect(await runKillAsleep(asleepCtx)).toBe(true);
        expect(calls).toEqual([['kill', 'u-1']]);
        expect(confirm.mock.calls[0]?.[5]).toBe('danger');
        expect(String(confirm.mock.calls[0]?.[1])).toContain('agent a');
        expect(refreshes).toBe(1);
    });

    it('a cancel calls nothing', async () => {
        standUp({ killAsleepSession: async () => { calls.push(['kill']); } }, { App: { showConfirmModal: async () => false } });
        expect(await runKillAsleep(asleepCtx)).toBe(false);
        expect(calls).toEqual([]);
    });

    it('a refusal is said and the list still refreshes', async () => {
        standUp({ killAsleepSession: async () => { throw new Error('not asleep'); } }, { App: { showConfirmModal: async () => true } });
        expect(await runKillAsleep(asleepCtx)).toBe(false);
        expect(said[0]).toContain('not asleep');
        expect(refreshes).toBe(1);
    });
});

describe('runReopen and runArchive (#1845)', () => {
    it('reopen restarts the stored session, then focuses it like a wake', async () => {
        const focus: unknown[][] = [];
        standUp({ restartSession: async (u: string) => { calls.push(['restart', u]); } },
            { NavigationGeneration: { begin: (l: string) => l }, WakeFocus: { afterWake: (...a: unknown[]) => focus.push(a) } });
        expect(await runReopen(CTX)).toBe(true);
        expect(calls).toEqual([['restart', 'u-a']]);
        expect(focus).toEqual([['u-a', 'reopen:carnivore_a']]);
    });

    it('a failed reopen says why and focuses nothing', async () => {
        const focus: unknown[][] = [];
        standUp({ restartSession: async () => { throw new Error('no such record'); } }, { WakeFocus: { afterWake: (...a: unknown[]) => focus.push(a) } });
        expect(await runReopen(CTX)).toBe(false);
        expect(said[0]).toContain('no such record');
        expect(focus).toEqual([]);
    });

    it('archive soft-deletes the record and repaints', async () => {
        standUp({ deleteSessionRecord: async (u: string) => { calls.push(['archive', u]); } });
        expect(await runArchive(CTX)).toBe(true);
        expect(calls).toEqual([['archive', 'u-a']]);
        expect(refreshes).toBe(1);
    });

    it('a failed archive says why', async () => {
        standUp({ deleteSessionRecord: async () => { throw new Error('locked'); } });
        expect(await runArchive(CTX)).toBe(false);
        expect(said[0]).toContain('locked');
    });
});
