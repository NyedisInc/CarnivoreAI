/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { fakeStorage } from './test-support';
import {
    LAST_VIEW_KEY, forgetLastView, readLastView, rememberLastView, restoreLastView, watchSessionDestroyed, type RestoreDeps,
} from './last-view';

let store = fakeStorage();

beforeEach(() => {
    store = fakeStorage();
    setDrawerEnv({ localStorage: store });
});
afterEach(() => setDrawerEnv(null));

function deps(over: Partial<RestoreDeps> = {}): RestoreDeps {
    return {
        screen: () => 'launchpad',
        rows: () => [{ name: 'carnivore_a', session_id: 'ses_a' }],
        hasLayout: () => true,
        openSession: vi.fn(() => true),
        openLayout: vi.fn(),
        ...over,
    };
}

describe('storage', () => {
    it('round trips a session and a layout', () => {
        rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        expect(readLastView()).toEqual({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        rememberLastView({ kind: 'layout', uuid: 'u1' });
        expect(readLastView()).toEqual({ kind: 'layout', uuid: 'u1' });
        forgetLastView();
        expect(readLastView()).toBeNull();
    });
    it('reads junk as nothing', () => {
        store.setItem(LAST_VIEW_KEY, '{nope');
        expect(readLastView()).toBeNull();
        store.setItem(LAST_VIEW_KEY, JSON.stringify({ kind: 'layout' }));
        expect(readLastView()).toBeNull();
    });
    it('never throws when storage refuses', () => {
        setDrawerEnv({ localStorage: fakeStorage({}, true) });
        expect(() => rememberLastView({ kind: 'layout', uuid: 'u1' })).not.toThrow();
        expect(readLastView()).toBeNull();
        expect(() => forgetLastView()).not.toThrow();
    });
});

describe('restoreLastView', () => {
    it('does nothing off Home', () => {
        rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        const d = deps({ screen: () => 'terminal' });
        expect(restoreLastView(d)).toBe(false);
        expect(d.openSession).not.toHaveBeenCalled();
    });
    it('does nothing with nothing remembered', () => {
        const d = deps();
        expect(restoreLastView(d)).toBe(false);
        expect(d.openSession).not.toHaveBeenCalled();
    });
    it('opens a live session by id', () => {
        rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        const d = deps();
        expect(restoreLastView(d)).toBe(true);
        expect(d.openSession).toHaveBeenCalledWith('ses_a', 'carnivore_a');
    });
    it('forgets a session with no awake row and opens nothing', () => {
        rememberLastView({ kind: 'session', sessionId: 'ses_gone', tmuxName: 'carnivore_gone' });
        const d = deps();
        expect(restoreLastView(d)).toBe(false);
        expect(d.openSession).not.toHaveBeenCalled();
        expect(readLastView()).toBeNull();
        rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        expect(restoreLastView(deps({ rows: () => [{ name: 'carnivore_a', session_id: 'ses_a', asleep: true }] }))).toBe(false);
    });
    it('opens a held Layout, forgets a missing one, and tries an unloaded list', () => {
        rememberLastView({ kind: 'layout', uuid: 'u1' });
        const d = deps();
        expect(restoreLastView(d)).toBe(true);
        expect(d.openLayout).toHaveBeenCalledWith('u1');
        const gone = deps({ hasLayout: () => false });
        expect(restoreLastView(gone)).toBe(false);
        expect(gone.openLayout).not.toHaveBeenCalled();
        expect(readLastView()).toBeNull();
        rememberLastView({ kind: 'layout', uuid: 'u1' });
        const unloaded = deps({ hasLayout: () => null });
        expect(restoreLastView(unloaded)).toBe(true);
    });
    it('layout: an unloaded list keeps the record and defers to openLayout, loaded-and-missing forgets, present restores', () => {
        rememberLastView({ kind: 'layout', uuid: 'u1' });
        const unloaded = deps({ hasLayout: () => null });
        expect(restoreLastView(unloaded)).toBe(true);
        expect(unloaded.openLayout).toHaveBeenCalledWith('u1');
        expect(readLastView()).toEqual({ kind: 'layout', uuid: 'u1' });
        const missing = deps({ hasLayout: () => false });
        expect(restoreLastView(missing)).toBe(false);
        expect(missing.openLayout).not.toHaveBeenCalled();
        expect(readLastView()).toBeNull();
        rememberLastView({ kind: 'layout', uuid: 'u1' });
        const present = deps({ hasLayout: (u) => u === 'u1' });
        expect(restoreLastView(present)).toBe(true);
        expect(present.openLayout).toHaveBeenCalledWith('u1');
    });
    it('keeps the record and opens nothing while the row list is not loaded', () => {
        rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        const d = deps({ rows: () => [] });
        expect(restoreLastView(d)).toBe(false);
        expect(d.openSession).not.toHaveBeenCalled();
        expect(readLastView()).toEqual({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
    });
    it('treats a dead-pane husk as gone: forgets and stays Home', () => {
        rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        const d = deps({ rows: () => [{ name: 'carnivore_a', session_id: 'ses_a', status: 'dead' }] });
        expect(restoreLastView(d)).toBe(false);
        expect(d.openSession).not.toHaveBeenCalled();
        expect(readLastView()).toBeNull();
    });
});

describe('watchSessionDestroyed', () => {
    it('forgets a remembered session when its terminal is destroyed, but keeps a Layout', () => {
        const target = new EventTarget();
        watchSessionDestroyed(target);
        rememberLastView({ kind: 'layout', uuid: 'u1' });
        target.dispatchEvent(new Event('session-destroyed'));
        expect(readLastView()).toEqual({ kind: 'layout', uuid: 'u1' });
        rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        target.dispatchEvent(new Event('session-destroyed'));
        expect(readLastView()).toBeNull();
    });
});

describe('watchSessionDestroyed: primary-session-gone', () => {
    const A = { kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' } as const;
    const B = { kind: 'session', sessionId: 'ses_b', tmuxName: 'carnivore_b' } as const;
    const gone = (target: EventTarget, detail?: object) => target.dispatchEvent(new CustomEvent('cloude:primary-session-gone', { detail }));

    it('forgets the record when the session that went is the remembered one', () => {
        const target = new EventTarget();
        watchSessionDestroyed(target);
        rememberLastView(A);
        gone(target, { tmuxName: 'carnivore_a' });
        expect(readLastView()).toBeNull();
        rememberLastView(A);
        gone(target, { sessionId: 'ses_a' });
        expect(readLastView()).toBeNull();
    });
    it('keeps the next tab when it was recorded before the event', () => {
        const target = new EventTarget();
        watchSessionDestroyed(target);
        rememberLastView(B);
        gone(target, { tmuxName: 'carnivore_a' });
        expect(readLastView()).toEqual(B);
    });
    it('keeps the next tab when a listener registered after ours records it during the same event', () => {
        const target = new EventTarget();
        watchSessionDestroyed(target);
        rememberLastView(A);
        target.addEventListener('cloude:primary-session-gone', () => rememberLastView(B));
        gone(target, { tmuxName: 'carnivore_a' });
        expect(readLastView()).toEqual(B);
    });
    it('keeps the next tab when a listener registered before ours records it during the same event', () => {
        const target = new EventTarget();
        target.addEventListener('cloude:primary-session-gone', () => rememberLastView(B));
        watchSessionDestroyed(target);
        rememberLastView(A);
        gone(target, { tmuxName: 'carnivore_a' });
        expect(readLastView()).toEqual(B);
    });
    it('keeps the record for another session, a Layout, or an event with no identity', () => {
        const target = new EventTarget();
        watchSessionDestroyed(target);
        rememberLastView(A);
        gone(target, { tmuxName: 'carnivore_z' });
        gone(target);
        expect(readLastView()).toEqual(A);
        rememberLastView({ kind: 'layout', uuid: 'u1' });
        gone(target, { tmuxName: 'carnivore_a' });
        expect(readLastView()).toEqual({ kind: 'layout', uuid: 'u1' });
    });
});
