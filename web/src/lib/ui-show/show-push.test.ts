/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const server = vi.hoisted(() => ({ show: null as Record<string, unknown> | null, reads: 0 }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string) => {
            if (p === '/ui/show') {
                server.reads += 1;
                return { show: server.show };
            }
            return {};
        },
    };
});

const wired = vi.hoisted(() => ({
    file: vi.fn(async () => true),
}));

vi.mock('./selectors', () => ({
    browserSelectors: () => ({
        session: vi.fn(async () => true), file: wired.file, browser: vi.fn(async () => true),
        board: vi.fn(async () => true), layout: vi.fn(async () => true), taskManager: vi.fn(async () => true),
    }),
}));

import { resourcePush } from '../resource-push/boot';
import type { ShowSelectors } from './selectors';
import { applyShow, followUiShow, resetUiShowForTest, UI_SHOW_TOPIC, type ShowPointer } from './show-push.svelte';

const ME = 'tab-aaaaaaaa-1';
const OTHER = 'tab-bbbbbbbb-2';

function spies() {
    return {
        session: vi.fn(async () => true), file: vi.fn(async () => true), browser: vi.fn(async () => true),
        board: vi.fn(async () => true), layout: vi.fn(async () => true), taskManager: vi.fn(async () => true),
    } satisfies ShowSelectors;
}

function pointer(over: Partial<ShowPointer> = {}): ShowPointer {
    return { seq: 10, kind: 'file', id: '0123456789abcdef', target_client_id: ME, age_s: 0.2, ...over };
}

beforeEach(() => {
    wired.file.mockClear();
    resetUiShowForTest();
    server.show = null;
    server.reads = 0;
});
afterEach(() => vi.restoreAllMocks());

describe('the addressed window shows each kind of item', () => {
    test.each([
        ['file', 'file', ['0123456789abcdef']],
        ['browser', 'browser', ['0123456789abcdef']],
        ['board', 'board', ['0123456789abcdef']],
        ['layout', 'layout', ['0123456789abcdef']],
    ] as const)('%s goes to its own selector with its id', async (kind, name, args) => {
        const s = spies();
        expect(await applyShow(pointer({ kind }), s, ME)).toBe(true);
        expect(s[name]).toHaveBeenCalledWith(...args);
        const others = Object.entries(s).filter(([k]) => k !== name);
        for (const [, spy] of others) expect(spy).not.toHaveBeenCalled();
    });

    test('a session carries its tmux name, the Task Manager no id', async () => {
        const s = spies();
        await applyShow(pointer({ kind: 'session', id: 'ses_1', tmux_session: 'carnivore_a' }), s, ME);
        expect(s.session).toHaveBeenCalledWith('ses_1', 'carnivore_a');
        await applyShow(pointer({ seq: 11, kind: 'task_manager', id: '' }), s, ME);
        expect(s.taskManager).toHaveBeenCalledWith();
    });
});

describe('every other window ignores it', () => {
    test('a pointer addressed to another window shows nothing here and does not use up its seq', async () => {
        const s = spies();
        expect(await applyShow(pointer({ target_client_id: OTHER }), s, ME)).toBe(false);
        expect(Object.values(s).every((spy) => spy.mock.calls.length === 0)).toBe(true);
        expect(await applyShow(pointer({ target_client_id: ME }), s, ME)).toBe(true);
        expect(s.file).toHaveBeenCalledTimes(1);
    });

    test('a window with no id yet (the terminal script has not loaded) shows nothing', async () => {
        const s = spies();
        expect(await applyShow(pointer(), s, null)).toBe(false);
        expect(s.file).not.toHaveBeenCalled();
    });

    test('a pointer with no addressee shows nothing', async () => {
        const s = spies();
        expect(await applyShow(pointer({ target_client_id: undefined }), s, ME)).toBe(false);
    });
});

describe('a pointer acts once and only while fresh', () => {
    test('the same seq twice shows once', async () => {
        const s = spies();
        await applyShow(pointer(), s, ME);
        expect(await applyShow(pointer(), s, ME)).toBe(false);
        expect(s.file).toHaveBeenCalledTimes(1);
    });

    test('a stale pointer (a reload long after) shows nothing, and a missing age shows nothing', async () => {
        const s = spies();
        expect(await applyShow(pointer({ age_s: 61 }), s, ME)).toBe(false);
        expect(await applyShow(pointer({ seq: 12, age_s: undefined }), s, ME)).toBe(false);
        expect(s.file).not.toHaveBeenCalled();
    });

    test('a selector that throws (the row closed meanwhile) answers false and leaves the next pointer able to show', async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => {});
        const s = spies();
        s.file.mockRejectedValueOnce(new Error('gone'));
        expect(await applyShow(pointer(), s, ME)).toBe(false);
        expect(await applyShow(pointer({ seq: 13 }), s, ME)).toBe(true);
    });
});

describe('the desktop app raises the window a show landed on (R1-13)', () => {
    const bridge = (raiseWindow: () => Promise<boolean>) => {
        (globalThis as unknown as { carnivoreDesktop?: unknown }).carnivoreDesktop = { capabilities: ['raiseWindow'], raiseWindow };
    };
    afterEach(() => { delete (globalThis as unknown as { carnivoreDesktop?: unknown }).carnivoreDesktop; });

    test('a fresh pointer addressed here that showed raises this window once; a browser tab with no bridge just shows', async () => {
        const raise = vi.fn(async () => true);
        bridge(raise);
        expect(await applyShow(pointer(), spies(), ME)).toBe(true);
        expect(raise).toHaveBeenCalledTimes(1);
        delete (globalThis as unknown as { carnivoreDesktop?: unknown }).carnivoreDesktop;
        expect(await applyShow(pointer({ seq: 11 }), spies(), ME)).toBe(true);
        expect(raise).toHaveBeenCalledTimes(1);
    });

    test('a foreign, stale, repeated or failed show raises nothing, and a raise that throws does not undo the show', async () => {
        vi.spyOn(console, 'debug').mockImplementation(() => {});
        const raise = vi.fn(async () => true);
        bridge(raise);
        const s = spies();
        await applyShow(pointer({ target_client_id: OTHER }), s, ME);
        await applyShow(pointer({ seq: 12, age_s: 61 }), s, ME);
        s.file.mockResolvedValueOnce(false);
        await applyShow(pointer({ seq: 13 }), s, ME);
        expect(raise).not.toHaveBeenCalled();
        await applyShow(pointer({ seq: 14 }), s, ME);
        expect(await applyShow(pointer({ seq: 14 }), s, ME)).toBe(false);
        expect(raise).toHaveBeenCalledTimes(1);
        bridge(vi.fn(async () => { throw new Error('ipc down'); }));
        expect(await applyShow(pointer({ seq: 15 }), s, ME)).toBe(true);
    });
});

describe('the push', () => {
    test('a ui_show frame reads the pointer and the addressed window shows it once; a pointer for another window does not', async () => {
        const g = globalThis as unknown as { TerminalSizeMaster?: { clientId(): string } };
        g.TerminalSizeMaster = { clientId: () => ME };
        followUiShow();
        for (let i = 0; i < 5; i += 1) await Promise.resolve();
        expect(wired.file).not.toHaveBeenCalled();
        const push = resourcePush();
        push.store.hello({ resource_topics: [UI_SHOW_TOPIC] });

        server.show = { ...pointer({ seq: 31 }) };
        push.store.frame({ topics: [UI_SHOW_TOPIC] });
        for (let i = 0; i < 10; i += 1) await Promise.resolve();
        expect(wired.file).toHaveBeenCalledTimes(1);

        push.store.frame({ topics: [UI_SHOW_TOPIC] });
        server.show = { ...pointer({ seq: 32, target_client_id: OTHER }) };
        push.store.frame({ topics: [UI_SHOW_TOPIC] });
        for (let i = 0; i < 10; i += 1) await Promise.resolve();
        expect(wired.file).toHaveBeenCalledTimes(1);
        delete g.TerminalSizeMaster;
    });
});
