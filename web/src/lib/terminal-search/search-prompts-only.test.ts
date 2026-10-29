import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { SearchController } from './search-controller.svelte';
import { SEARCH_PROMPTS_ONLY_KEY, uiPrefs } from '../ui/prefs.svelte';
import { t } from '../i18n/index.svelte';
import { harness } from './search-controller-harness';
import type { ScannedPrompt } from './types';

let open: SearchController | null = null;

const PROMPTS: ScannedPrompt[] = [
    { ordinal: 1, line: 10, text: 'hello world', full: 'hello world', preview: 'hello world' },
    { ordinal: 2, line: 20, text: 'fix the bug', full: 'fix the bug', preview: 'fix the bug' },
    { ordinal: 3, line: 30, text: 'fix another bug', full: 'fix another bug', preview: 'fix another bug' },
];

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    open?.close();
    open = null;
    vi.useRealTimers();
});

function fakeStorage(): { getItem: (k: string) => string | null; setItem: (k: string, v: string) => void } {
    const seen = new Map<string, string>();
    return {
        getItem: (k) => (seen.has(k) ? (seen.get(k) as string) : null),
        setItem: (k, v) => {
            seen.set(k, v);
        },
    };
}

describe('the prompts-only toggle', () => {
    beforeEach(() => {
        Object.defineProperty(globalThis, 'localStorage', {
            value: fakeStorage(),
            configurable: true,
            writable: true,
        });
        uiPrefs.resetForTests();
    });

    afterEach(() => {
        uiPrefs.resetForTests();
    });

    test('nothing stored means off', () => {
        const h = harness();
        expect(h.controller.promptsOnly).toBe(false);
    });

    test('the toggle flips it and writes it down', () => {
        const h = harness();
        open = h.controller;
        h.controller.togglePromptsOnly();
        expect(h.controller.promptsOnly).toBe(true);
        expect(localStorage.getItem(SEARCH_PROMPTS_ONLY_KEY)).toBe('1');
        h.controller.togglePromptsOnly();
        expect(h.controller.promptsOnly).toBe(false);
        expect(localStorage.getItem(SEARCH_PROMPTS_ONLY_KEY)).toBe('0');
    });

    test('a codex session is available too (issue #631)', () => {
        const h = harness({ agentFamily: 'codex' });
        open = h.controller;
        h.controller.open();
        expect(h.controller.promptsOnlyAvailable).toBe(true);
        expect(h.controller.promptsOnlyDisabledReason).toBeNull();
        h.controller.togglePromptsOnly();
        expect(h.controller.promptsOnly).toBe(true);
    });

    test('a claude session is available, with ONE title regardless of on/off (issue #650)', () => {
        const h = harness({ agentFamily: 'claude' });
        open = h.controller;
        h.controller.open();
        expect(h.controller.promptsOnlyAvailable).toBe(true);
        expect(h.controller.promptsOnlyDisabledReason).toBeNull();
        expect(h.controller.promptsOnlyTitle).toBe(t('search.prompts_only.toggle'));
        h.controller.togglePromptsOnly();
        expect(h.controller.promptsOnlyTitle).toBe(t('search.prompts_only.toggle'));
    });

    describe('stepping through prompts only', () => {
        test('OFF: enter and shift+enter still drive the xterm add-on, unchanged', () => {
            const h = harness({ scannedPrompts: PROMPTS });
            open = h.controller;
            h.controller.open();
            h.controller.query = 'fix';
            h.controller.step('next');
            expect(h.calls.prev).toBe(1);
            h.controller.step('prev');
            expect(h.calls.next).toBe(1);
        });

        test('ON: runQuery lands on the newest matching prompt, and the counter counts only matches', () => {
            const h = harness({ scannedPrompts: PROMPTS });
            open = h.controller;
            h.controller.open();
            h.controller.togglePromptsOnly();
            h.controller.query = 'fix';
            h.controller.runQuery();
            expect(h.controller.countText).toBe('2 of 2 prompts');
        });

        test('ON: runQuery never runs the add-on over the buffer, so terminal output is not highlighted', () => {
            const h = harness({ scannedPrompts: PROMPTS });
            open = h.controller;
            h.controller.open();
            h.controller.togglePromptsOnly();
            h.controller.query = 'fix';
            h.controller.runQuery();
            expect(h.calls.find).toEqual([]);
            expect(h.calls.clear).toBeGreaterThan(0);
            h.controller.togglePromptsOnly();
            expect(h.calls.find.length).toBe(1);
        });

        test('ON: enter and shift+enter walk the rail, never the add-on', () => {
            const h = harness({ scannedPrompts: PROMPTS });
            open = h.controller;
            h.controller.open();
            h.controller.togglePromptsOnly();
            h.controller.query = 'fix';
            h.controller.runQuery();
            expect(h.controller.countText).toBe('2 of 2 prompts');
            h.controller.step('next');
            expect(h.controller.countText).toBe('1 of 2 prompts');
            expect(h.calls.next).toBe(0);
            expect(h.calls.prev).toBe(0);
        });

        test('NEGATIVE: a query matching no prompt says so, and stepping goes nowhere', () => {
            const h = harness({ scannedPrompts: PROMPTS });
            open = h.controller;
            h.controller.open();
            h.controller.togglePromptsOnly();
            h.controller.query = 'nonexistent';
            h.controller.runQuery();
            expect(h.controller.countText).toBe('no prompts match');
            h.controller.step('next');
            expect(h.controller.countText).toBe('no prompts match');
        });
    });
});
