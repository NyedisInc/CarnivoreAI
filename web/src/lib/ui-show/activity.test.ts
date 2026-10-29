/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { ACTIVITY_THROTTLE_MS, startActivityReport, startGoneReport } from './activity';

function rig(clientId: string | null = 'tab-aaaaaaaa-1', focused = false) {
    vi.spyOn(document, 'hasFocus').mockReturnValue(focused);
    let at = 1_000_000;
    const post = vi.fn(async (_id: string): Promise<unknown> => ({}));
    const deps = { clientId: () => clientId, post, now: () => at };
    const stop = startActivityReport(window, deps);
    return { post, stop, advance: (ms: number) => { at += ms; } };
}

describe('activity reports', () => {
    afterEach(() => vi.restoreAllMocks());

    test('pointer down and key down report this window\'s id, once per throttle window', () => {
        const r = rig();
        window.dispatchEvent(new Event('pointerdown'));
        window.dispatchEvent(new Event('keydown'));
        window.dispatchEvent(new Event('pointerdown'));
        expect(r.post).toHaveBeenCalledTimes(1);
        expect(r.post).toHaveBeenCalledWith('tab-aaaaaaaa-1');
        r.advance(ACTIVITY_THROTTLE_MS - 1);
        window.dispatchEvent(new Event('keydown'));
        expect(r.post).toHaveBeenCalledTimes(1);
        r.advance(1);
        window.dispatchEvent(new Event('keydown'));
        expect(r.post).toHaveBeenCalledTimes(2);
        r.stop();
    });

    test('a window with no id yet sends nothing and keeps its throttle for the first real report', () => {
        const r = rig(null);
        window.dispatchEvent(new Event('pointerdown'));
        expect(r.post).not.toHaveBeenCalled();
        r.stop();
    });

    test('a failed post is swallowed and the next input after the throttle reports again', async () => {
        vi.spyOn(console, 'debug').mockImplementation(() => {});
        const r = rig();
        r.post.mockRejectedValueOnce(new Error('offline'));
        window.dispatchEvent(new Event('pointerdown'));
        await Promise.resolve();
        r.advance(ACTIVITY_THROTTLE_MS);
        window.dispatchEvent(new Event('pointerdown'));
        expect(r.post).toHaveBeenCalledTimes(2);
        r.stop();
    });

    test('stopping removes the listeners', () => {
        const r = rig();
        r.stop();
        window.dispatchEvent(new Event('pointerdown'));
        expect(r.post).not.toHaveBeenCalled();
    });
});

describe('the gone report (R1-13)', () => {
    afterEach(() => document.documentElement.removeAttribute('data-solo'));

    test('pagehide sends this window\'s id once; no id yet sends nothing; stopping removes the listener', () => {
        const post = vi.fn(async (_id: string): Promise<unknown> => ({}));
        const stop = startGoneReport(window, { clientId: () => 'tab-aaaaaaaa-1', post });
        window.dispatchEvent(new Event('pagehide'));
        expect(post).toHaveBeenCalledTimes(1);
        expect(post).toHaveBeenCalledWith('tab-aaaaaaaa-1');
        stop();
        window.dispatchEvent(new Event('pagehide'));
        expect(post).toHaveBeenCalledTimes(1);
        const none = vi.fn();
        const stopNone = startGoneReport(window, { clientId: () => null, post: none });
        window.dispatchEvent(new Event('pagehide'));
        expect(none).not.toHaveBeenCalled();
        stopNone();
    });

    test('a failed or throwing post is swallowed', async () => {
        vi.spyOn(console, 'debug').mockImplementation(() => {});
        const stop = startGoneReport(window, { clientId: () => 'tab-aaaaaaaa-1', post: () => { throw new Error('boom'); } });
        expect(() => window.dispatchEvent(new Event('pagehide'))).not.toThrow();
        stop();
        const stopRejecting = startGoneReport(window, { clientId: () => 'tab-aaaaaaaa-1', post: async () => { throw new Error('offline'); } });
        expect(() => window.dispatchEvent(new Event('pagehide'))).not.toThrow();
        await Promise.resolve();
        stopRejecting();
    });

    test('a solo-terminal window reports neither activity nor gone', () => {
        document.documentElement.setAttribute('data-solo', '');
        const post = vi.fn(async (_id: string): Promise<unknown> => ({}));
        const stopActivity = startActivityReport(window, { clientId: () => 'tab-aaaaaaaa-1', post, now: () => 5_000_000 });
        const gone = vi.fn();
        const stopGone = startGoneReport(window, { clientId: () => 'tab-aaaaaaaa-1', post: gone });
        window.dispatchEvent(new Event('pointerdown'));
        window.dispatchEvent(new Event('pagehide'));
        expect(post).not.toHaveBeenCalled();
        expect(gone).not.toHaveBeenCalled();
        stopActivity();
        stopGone();
    });
});

describe('reload and cache restore (R1-BR-FIX C4)', () => {
    afterEach(() => vi.restoreAllMocks());

    test('a cached pagehide (persisted) sends no gone report; a real close still does', () => {
        const post = vi.fn(async (_id: string): Promise<unknown> => ({}));
        const stop = startGoneReport(window, { clientId: () => 'tab-aaaaaaaa-1', post });
        window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
        expect(post).not.toHaveBeenCalled();
        window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }));
        expect(post).toHaveBeenCalledTimes(1);
        stop();
    });

    test('a focused window reports activity once at boot and once on pageshow; an unfocused one stays quiet', () => {
        const quiet = rig('tab-aaaaaaaa-1', false);
        window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
        expect(quiet.post).not.toHaveBeenCalled();
        quiet.stop();

        const loud = rig('tab-aaaaaaaa-1', true);
        expect(loud.post).toHaveBeenCalledTimes(1);
        loud.advance(ACTIVITY_THROTTLE_MS);
        window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
        expect(loud.post).toHaveBeenCalledTimes(2);
        loud.stop();
    });
});
