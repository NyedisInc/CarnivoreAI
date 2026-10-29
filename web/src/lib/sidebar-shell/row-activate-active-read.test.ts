/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { activateRow } from './row-activate';

const g = globalThis as Record<string, unknown>;
let row: HTMLElement;
let ctrl: { _activeTmuxName: string | null; _pendingSelection: null; _closeAfterSwitch: ReturnType<typeof vi.fn> };
let begin: ReturnType<typeof vi.fn>;

beforeEach(() => {
    begin = vi.fn();
    g.NavigationGeneration = { begin, isCurrent: () => true, keep: () => true };
    g.App = { currentScreen: 'terminal', returnToExistingTerminal: vi.fn() };
    g.API = {
        getSession: vi.fn(), adoptSession: vi.fn(), setSessionUnread: vi.fn(async () => ({ success: true })),
    };
    ctrl = { _activeTmuxName: 'cloude_a', _pendingSelection: null, _closeAfterSwitch: vi.fn() };
    row = document.body.appendChild(document.createElement('div'));
    row.dataset.name = 'cloude_a';
    row.dataset.sessionId = 'ses_a';
});
afterEach(() => {
    document.body.replaceChildren();
    for (const k of ['NavigationGeneration', 'App', 'API']) delete g[k];
});

describe('click on the already active row', () => {
    it('marks it read and does not navigate', async () => {
        await activateRow(ctrl as never, row);
        const api = g.API as Record<string, ReturnType<typeof vi.fn>>;
        expect(api.setSessionUnread).toHaveBeenCalledExactlyOnceWith('cloude_a', false);
        expect(begin).not.toHaveBeenCalled();
        expect(api.getSession).not.toHaveBeenCalled();
        expect(api.adoptSession).not.toHaveBeenCalled();
        expect((g.App as { returnToExistingTerminal: unknown }).returnToExistingTerminal).not.toHaveBeenCalled();
    });

    it('a different row does not send the write from this path', async () => {
        ctrl._activeTmuxName = 'cloude_b';
        const api = g.API as Record<string, ReturnType<typeof vi.fn>>;
        api.getSession!.mockResolvedValue(null);
        await activateRow(ctrl as never, row);
        expect(api.setSessionUnread).not.toHaveBeenCalled();
        expect(begin).toHaveBeenCalledOnce();
    });
});
