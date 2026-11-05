// @vitest-environment jsdom
import { createRequire } from 'node:module';
import { describe, expect, it, vi } from 'vitest';
import { installAppKeys, type AppChord } from './router';
import { APP_CHORDS } from './chords';
import { createFocusHistory } from '../focus-history/focus-history';

const require = createRequire(import.meta.url);
const { RESERVED_CHORDS, normalize } = require('../../../../macOS/app-menu/chords.js');

function chord(run: AppChord['run']): AppChord {
    return { id: 't', key: '[', meta: true, accelerator: 'Cmd+[', keys: 'cmd [', labelKey: 'x', run };
}

function press(target: Element, init: KeyboardEventInit): KeyboardEvent {
    const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
    target.dispatchEvent(event);
    return event;
}

describe('app key router', () => {
    it('fires the chord before the terminal sees it, and only that exact chord', () => {
        const run = vi.fn();
        const stop = installAppKeys([chord(run)], document);
        const term = document.createElement('div');
        term.className = 'xterm';
        const pane = document.createElement('textarea');
        pane.className = 'xterm-helper-textarea';
        term.appendChild(pane);
        document.body.appendChild(term);
        const reachedTerminal = vi.fn();
        pane.addEventListener('keydown', reachedTerminal);

        const hit = press(pane, { key: '[', metaKey: true });
        expect(run).toHaveBeenCalledTimes(1);
        expect(hit.defaultPrevented).toBe(true);
        expect(reachedTerminal).not.toHaveBeenCalled();

        press(pane, { key: '[', metaKey: true, shiftKey: true });
        press(pane, { key: '[', ctrlKey: true });
        expect(run).toHaveBeenCalledTimes(1);
        expect(reachedTerminal).toHaveBeenCalledTimes(2);

        stop();
        press(pane, { key: '[', metaKey: true });
        expect(run).toHaveBeenCalledTimes(1);
        term.remove();
    });

    it('leaves a text field and an input method alone', () => {
        const run = vi.fn();
        const stop = installAppKeys([chord(run)], document);
        const field = document.createElement('input');
        document.body.appendChild(field);
        const typed = press(field, { key: '[', metaKey: true });
        press(document.body, { key: '[', metaKey: true, isComposing: true });
        expect(run).not.toHaveBeenCalled();
        expect(typed.defaultPrevented).toBe(false);
        stop();
        field.remove();
    });

    it('a chord whose action declines lets the key through', () => {
        const stop = installAppKeys([chord(() => false)], document);
        expect(press(document.body, { key: '[', metaKey: true }).defaultPrevented).toBe(false);
        stop();
    });

    it('every app chord is reserved in the Electron chord audit', () => {
        const reserved = new Set(RESERVED_CHORDS.map((r: { chord: string }) => normalize(r.chord).canon));
        for (const c of APP_CHORDS) expect(reserved.has(normalize(c.accelerator).canon), c.accelerator).toBe(true);
        expect(new Set(APP_CHORDS.map((c) => c.id)).size).toBe(APP_CHORDS.length);
    });
});

describe('focus history', () => {
    const s = (id: string) => ({ kind: 'session' as const, id, tmuxName: id });
    const live = () => true;

    it('walks back and forward, skips the gone, and a fresh visit drops the forward list', () => {
        const h = createFocusHistory(3);
        h.visit(s('a')); h.visit(s('b')); h.visit(s('b')); h.visit(s('c'));
        expect(h.entries().map((e) => (e as { id: string }).id)).toEqual(['a', 'b', 'c']);
        expect(h.step(-1, (e) => (e as { id: string }).id !== 'b')).toEqual(s('a'));
        h.visit(s('a'));
        expect(h.cursor()).toBe(0);
        expect(h.step(1, live)).toEqual(s('b'));
        h.visit(s('b'));
        h.visit(s('d'));
        expect(h.entries().map((e) => (e as { id: string }).id)).toEqual(['a', 'b', 'd']);
        expect(h.step(1, live)).toBeNull();
        h.visit(s('e'));
        expect(h.entries().length).toBe(3);
    });
});
