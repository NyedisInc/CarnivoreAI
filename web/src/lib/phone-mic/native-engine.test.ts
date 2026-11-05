/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMic } from './controller.svelte';
import { nativeStarter } from './engines';
import { bootNativeShell, parseFromNative } from '../native-shell/shell';

function fakeShell() {
    const posted: string[] = [];
    const w = globalThis as unknown as Record<string, { receive?: (m: unknown) => void } | unknown>;
    w.carnivoreShell = { version: 1, platform: 'ios' };
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
});
