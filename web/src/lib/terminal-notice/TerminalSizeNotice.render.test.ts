/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TerminalSizeNotice from './TerminalSizeNotice.svelte';
import { i18n, setLocale } from '../i18n/index.svelte';

setLocale('en');

type Handle = { setGrid?: (next: { cols: number; rows: number } | null) => void };
let panel: Handle | null = null;

function paint(): Handle {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(TerminalSizeNotice, { target }) as never;
    flushSync();
    return panel;
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('the size notice', () => {
    test('paints nothing until it is given a grid', () => {
        paint();
        expect(document.querySelector('.terminal-size-notice')).toBeNull();
    });

    test('names the grid the pane is held at, from the catalog', () => {
        const instance = paint();
        instance.setGrid?.({ cols: 82, rows: 30 });
        flushSync();
        const text = document.querySelector('.terminal-size-notice')?.textContent?.trim();
        expect(text).toBe(i18n.t('terminal.size.constrained', { cols: 82, rows: 30 }));
        expect(text).toContain('82x30');
    });

    test('null hides it again', () => {
        const instance = paint();
        instance.setGrid?.({ cols: 82, rows: 30 });
        flushSync();
        instance.setGrid?.(null);
        flushSync();
        expect(document.querySelector('.terminal-size-notice')).toBeNull();
    });
});
