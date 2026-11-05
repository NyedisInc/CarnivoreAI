/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

import { WATCHED_EVENT, computeWatched, quietWatched, startWatchedSession } from './quiet-watched.svelte';
import { startPresenceBeacon } from './presence';

let stops: Array<() => void> = [];
afterEach(() => { stops.forEach((s) => s()); stops = []; document.body.innerHTML = ''; quietWatched.on = true; vi.restoreAllMocks(); });

function mountTerminal(): { term: HTMLTextAreaElement; other: HTMLButtonElement } {
    document.body.innerHTML = '<div class="xterm"><textarea id="t"></textarea></div><button id="b">home</button>';
    return { term: document.getElementById('t') as HTMLTextAreaElement, other: document.getElementById('b') as HTMLButtonElement };
}

describe('watched session', () => {
    test('only a focused terminal in a focused, visible window with the setting on is watched', () => {
        const { term, other } = mountTerminal();
        vi.spyOn(document, 'hasFocus').mockReturnValue(true);
        term.focus();
        expect(computeWatched(document, () => 'ses_7')).toBe('ses_7');
        other.focus();
        expect(computeWatched(document, () => 'ses_7')).toBe('');
        term.focus();
        vi.spyOn(document, 'hasFocus').mockReturnValue(false);
        expect(computeWatched(document, () => 'ses_7')).toBe('');
        vi.spyOn(document, 'hasFocus').mockReturnValue(true);
        quietWatched.on = false;
        expect(computeWatched(document, () => 'ses_7')).toBe('');
    });

    test('the beacon carries the watched id, posted on each switch by event, not by a timer', () => {
        const { term, other } = mountTerminal();
        vi.spyOn(document, 'hasFocus').mockReturnValue(true);
        const setInterval = vi.spyOn(window, 'setInterval');
        const posts: Array<[boolean, string]> = [];
        const desktop: string[] = [];
        (window as unknown as { carnivoreDesktop: unknown }).carnivoreDesktop = { watching: (id: string) => desktop.push(id) };
        let session = 'ses_a';
        stops.push(startWatchedSession({ sessionOf: () => session }));
        expect(setInterval).not.toHaveBeenCalled();
        stops.push(startPresenceBeacon({ clientId: () => 'tab-12345678', post: (_id, active, watched) => posts.push([active, watched]) }));
        document.dispatchEvent(new Event('keydown'));
        term.focus();
        session = 'ses_b';
        window.dispatchEvent(new Event('focus'));
        other.focus();
        expect(posts.slice(1)).toEqual([[true, 'ses_a'], [true, 'ses_b'], [true, '']]);
        expect(desktop).toEqual(['ses_a', 'ses_b', '']);
        let heard = 0;
        window.addEventListener(WATCHED_EVENT, () => { heard += 1; });
        other.focus();
        expect(heard).toBe(0);
        delete (window as unknown as { carnivoreDesktop?: unknown }).carnivoreDesktop;
    });
});
