/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sleeper = vi.hoisted(() => ({
    runWake: vi.fn(async () => true),
    runWakeWithId: vi.fn(async () => ({ started: true, sessionId: 'ses_live' as string | null })),
}));
vi.mock('../../drawer/row-menu-sleep', () => sleeper);
import { setDrawerEnv } from '../../drawer/env';
import type { RowMenuCtx } from '../row-context';
import { runFork } from './rename-fork';

const ctx = (over: Record<string, unknown> = {}): RowMenuCtx => ({ name: 'cloude_a', label: 'a', hostKey: 'local', projectId: null, ...over }) as unknown as RowMenuCtx;

let said: string[];
let picker: ReturnType<typeof vi.fn>;
let listeners: Array<(names: string[]) => void>;
let listed: unknown[];

const liveListing = (tmuxName: string, id: string): unknown => ({ session_uuid: null, tmux_session: tmuxName, session: { id } });

function page(): void {
    setDrawerEnv({
        CloudeI18n: { t: (k: string) => k },
        Launchpad: { showError: (t: string) => said.push(t) },
        CloudeWeb: { openForkPicker: picker },
        ListingPush: {
            isLive: () => true,
            rows: () => listed,
            onChange: (fn: (names: string[]) => void) => { listeners.push(fn); return () => { listeners = listeners.filter((l) => l !== fn); }; },
        },
    });
}

function fireChange(): void {
    for (const fn of [...listeners]) fn(['list']);
}

beforeEach(() => {
    vi.useFakeTimers();
    said = [];
    picker = vi.fn();
    listeners = [];
    listed = [];
    sleeper.runWake.mockResolvedValue(true);
    sleeper.runWakeWithId.mockReset();
    sleeper.runWakeWithId.mockResolvedValue({ started: true, sessionId: 'ses_live' });
    page();
});
afterEach(() => { vi.useRealTimers(); setDrawerEnv(null); });

describe('runFork on an asleep row', () => {
    it('opens the picker for the session id the wake answered with, without waiting on the listing', async () => {
        await runFork(ctx({ asleep: true, sessionUuid: 'u1' }));
        expect(sleeper.runWakeWithId).toHaveBeenCalledTimes(1);
        expect(picker).toHaveBeenCalledWith('ses_live', 'a');
        expect(listeners).toHaveLength(0);
    });

    it('with no id in the wake answer, opens when the pushed listing shows the row (matched by tmux name, session_uuid null)', async () => {
        sleeper.runWakeWithId.mockResolvedValue({ started: true, sessionId: null });
        const done = runFork(ctx({ asleep: true, sessionUuid: 'u1' }));
        await vi.advanceTimersByTimeAsync(0);
        expect(picker).not.toHaveBeenCalled();
        listed = [liveListing('cloude_a', 'ses_listed')];
        fireChange();
        await done;
        expect(picker).toHaveBeenCalledWith('ses_listed', 'a');
        expect(listeners).toHaveLength(0);
    });

    it('with no id, opens at once when the live row is already listed', async () => {
        sleeper.runWakeWithId.mockResolvedValue({ started: true, sessionId: null });
        listed = [liveListing('cloude_a', 'ses_listed')];
        await runFork(ctx({ asleep: true, sessionUuid: 'u1' }));
        expect(picker).toHaveBeenCalledWith('ses_listed', 'a');
    });

    it('with no id and no listing, reports the fork unavailable within the bound and lets go of the listener', async () => {
        sleeper.runWakeWithId.mockResolvedValue({ started: true, sessionId: null });
        const done = runFork(ctx({ asleep: true, sessionUuid: 'u1' }));
        await vi.advanceTimersByTimeAsync(31_000);
        await done;
        expect(picker).not.toHaveBeenCalled();
        expect(said).toEqual(['session.fork_to.unavailable']);
        expect(listeners).toHaveLength(0);
    });

    it('does not open anything when the wake did not start', async () => {
        sleeper.runWakeWithId.mockResolvedValue({ started: false, sessionId: null });
        await runFork(ctx({ asleep: true, sessionUuid: 'u1' }));
        expect(picker).not.toHaveBeenCalled();
        expect(listeners).toHaveLength(0);
    });
});

describe('runFork on a live row', () => {
    it('opens the picker for its own id', async () => {
        await runFork(ctx({ sessionId: 'ses_x' }));
        expect(picker).toHaveBeenCalledWith('ses_x', 'a');
        expect(sleeper.runWakeWithId).not.toHaveBeenCalled();
    });
});
