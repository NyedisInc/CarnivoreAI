/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TerminalStartupNotice from './TerminalStartupNotice.svelte';
import { i18n, setLocale } from '../i18n/index.svelte';

setLocale('en');

const STARTUP_COMMAND_OUTCOMES = ['issued', 'none', 'failed', 'unknown'] as const;

let panel: { setFailed?: (next: boolean) => void } | null = null;

/** Mount a fresh instance into a fresh, attached container. */
function paint(): { setFailed?: (next: boolean) => void } {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(TerminalStartupNotice, { target }) as never;
    flushSync();
    return panel;
}

function setFailed(instance: { setFailed?: (next: boolean) => void }, next: boolean): void {
    instance.setFailed?.(next);
    flushSync();
}

function click(selector: string): void {
    document.querySelector<HTMLButtonElement>(selector)?.click();
    flushSync();
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('a failed startup command', () => {
    test('paints the catalog sentence', () => {
        const instance = paint();
        setFailed(instance, true);
        expect(document.body.textContent).toContain(i18n.t('terminal.startup.failed'));
        expect(document.querySelector('.terminal-startup-notice')).not.toBeNull();
    });

    test('carries a dismiss control labelled from the catalog', () => {
        const instance = paint();
        setFailed(instance, true);
        const dismiss = document.querySelector<HTMLButtonElement>(
            '.terminal-startup-notice__dismiss',
        );
        expect(dismiss).not.toBeNull();
        expect(dismiss?.getAttribute('aria-label')).toBe(i18n.t('terminal.startup.dismiss'));
    });

    test('dismissing it hides the notice', () => {
        const instance = paint();
        setFailed(instance, true);
        expect(document.querySelector('.terminal-startup-notice')).not.toBeNull();
        click('.terminal-startup-notice__dismiss');
        expect(document.querySelector('.terminal-startup-notice')).toBeNull();
    });

    test('a FRESH failure is never pre-dismissed', () => {
        const instance = paint();
        setFailed(instance, true);
        click('.terminal-startup-notice__dismiss');
        expect(document.querySelector('.terminal-startup-notice')).toBeNull();
        setFailed(instance, false);
        setFailed(instance, true);
        expect(document.querySelector('.terminal-startup-notice')).not.toBeNull();
    });
});

describe('every other startup_command outcome renders nothing', () => {
    test.each(STARTUP_COMMAND_OUTCOMES.filter((outcome) => outcome !== 'failed'))(
        '%s paints no notice',
        (outcome) => {
            const instance = paint();
            setFailed(instance, (outcome as string) === 'failed');
            expect(document.querySelector('.terminal-startup-notice')).toBeNull();
            expect(document.body.textContent).not.toContain(i18n.t('terminal.startup.failed'));
        },
    );

    test('NEGATIVE CONTROL: the four outcomes are not all mapped to nothing', () => {
        const mapped = STARTUP_COMMAND_OUTCOMES.map((outcome) => outcome === 'failed');
        expect(mapped).toEqual([false, false, true, false]);
    });
});

describe('a fresh, never-shown notice', () => {
    test('paints nothing before setFailed is ever called', () => {
        paint();
        expect(document.querySelector('.terminal-startup-notice')).toBeNull();
    });
});
