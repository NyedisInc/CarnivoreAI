/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMic } from './controller.svelte';
import { nativeStarter, utteranceJoiner } from './engines';
import { bootNativeShell, parseFromNative } from '../native-shell/shell';

function fakeShell() {
    const posted: string[] = [];
    const w = globalThis as unknown as Record<string, { receive?: (m: unknown) => void } | unknown>;
    w.carnivoreShell = { version: 1, platform: 'ios', speech: true };
    w.webkit = { messageHandlers: { carnivore: { postMessage: (m: { type: string }) => { if (m.type.startsWith('speech')) posted.push(m.type); } } } };
    bootNativeShell();
    const fromNative = (m: object) => (w.carnivoreShell as { receive: (m: unknown) => void }).receive({ v: 1, ...m });
    return { posted, fromNative };
}

afterEach(() => { const w = globalThis as unknown as Record<string, unknown>; delete w.carnivoreShell; delete w.webkit; });

describe('native iPhone dictation engine', () => {
    it('is null in a plain browser and chosen inside the shell', () => {
        expect(nativeStarter()).toBeNull();
        fakeShell();
        expect(nativeStarter()).not.toBeNull();
    });

    it('an older app build (version 1, no speech flag) never gets the native engine', () => {
        const w = globalThis as unknown as Record<string, unknown>;
        w.carnivoreShell = { version: 1, platform: 'ios' };
        w.webkit = { messageHandlers: { carnivore: { postMessage: () => {} } } };
        expect(nativeStarter()).toBeNull();
    });

    it('partials reach the strip, send pastes the final text, cancel discards', () => {
        const { posted, fromNative } = fakeShell();
        const deliver = vi.fn();
        const mic = createMic({ claim: () => 't1', deliver, speech: nativeStarter(), record: null, transcribeReady: async () => true });
        mic.start();
        expect(mic.state.live).toBe(true);
        fromNative({ type: 'speech', kind: 'text', text: 'list the fil' });
        expect(mic.state.transcript).toBe('list the fil');
        mic.done();
        fromNative({ type: 'speech', kind: 'end', text: 'list the files' });
        expect(posted).toEqual(['speechStart', 'speechStop']);
        expect(deliver).toHaveBeenCalledWith('list the files', 't1');
        mic.start();
        fromNative({ type: 'speech', kind: 'text', text: 'never mind' });
        mic.cancel();
        expect(posted.at(-1)).toBe('speechCancel');
        expect(deliver).toHaveBeenCalledTimes(1);
    });

    it('a denied permission shows the blocked reason and pastes nothing', () => {
        const { fromNative } = fakeShell();
        const deliver = vi.fn();
        const mic = createMic({ claim: () => 't1', deliver, speech: nativeStarter(), record: null, transcribeReady: async () => true });
        mic.start();
        fromNative({ type: 'speech', kind: 'error', reason: 'denied' });
        expect(mic.state.phase).toBe('message');
        expect(mic.state.reason).toBe('blocked');
        expect(deliver).not.toHaveBeenCalled();
    });

    it('parses speech messages and drops bad kinds', () => {
        expect(parseFromNative({ v: 1, type: 'speech', kind: 'error', reason: 'denied' })).toMatchObject({ kind: 'error', reason: 'denied' });
        expect(parseFromNative({ v: 1, type: 'speech', kind: 'bogus' })).toBeNull();
    });

    it('keeps the words before a pause, never doubles a revision or an accumulating stream', () => {
        const { fromNative } = fakeShell();
        const deliver = vi.fn();
        const mic = createMic({ claim: () => 't1', deliver, speech: nativeStarter(), record: null, transcribeReady: async () => true });
        mic.start();
        for (const text of ['so the', 'so the plan is', 'so the plan is to ship', '', 'so friday', 'so friday at noon']) fromNative({ type: 'speech', kind: 'text', text });
        expect(mic.state.transcript).toBe('so the plan is to ship so friday at noon');
        mic.done();
        fromNative({ type: 'speech', kind: 'end', text: 'so friday at noon sharp' });
        expect(deliver).toHaveBeenCalledWith('so the plan is to ship so friday at noon sharp', 't1');
    });

    it('joiner: revisions pass through, an empty text is the boundary, an accumulating stream never doubles', () => {
        const j = utteranceJoiner();
        expect(j.feed('so the plan is to ship')).toBe('so the plan is to ship');
        expect(j.feed('So the plan is to ship it.')).toBe('So the plan is to ship it.');
        expect(j.feed('x b')).toBe('x b');
        const k = utteranceJoiner();
        k.feed('one two');
        expect(k.feed('')).toBe('one two');
        expect(k.feed('')).toBe('one two');
        expect(k.feed('three')).toBe('one two three');
        expect(k.feed('')).toBe('one two three');
        expect(k.feed('four')).toBe('one two three four');
        const m = utteranceJoiner();
        m.feed('one two');
        m.feed('');
        expect(m.feed('one two three')).toBe('one two three');
        expect(utteranceJoiner().feed('')).toBe('');
    });
});
