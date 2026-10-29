/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { activateRow } from './row-activate';
import { HOME_IN_MAIN_CLASS, initHomeInMain } from '../launchpad/home-in-main';

const g = globalThis as Record<string, unknown>;
let stop: () => void = () => {};
let row: HTMLElement;
let ctrl: { _activeTmuxName: string | null; _pendingSelection: null; _closeAfterSwitch: ReturnType<typeof vi.fn> };

function showTerminal(): void {
    document.getElementById('launchpad-screen')!.classList.remove('active');
    const terminal = document.getElementById('terminal-screen')!;
    terminal.classList.remove('active');
    terminal.classList.add('active');
    (g.App as { currentScreen: string }).currentScreen = 'terminal';
}

beforeEach(() => {
    vi.stubGlobal('innerWidth', 1300);
    vi.stubGlobal('innerHeight', 800);
    document.body.innerHTML = `
      <div id="terminal-screen" class="screen active"><div id="terminal-grid"><div class="oc-surface"></div></div></div>
      <div id="launchpad-screen" class="screen"></div>`;
    document.querySelector<HTMLElement>('.oc-surface')!.getBoundingClientRect = () =>
        ({ top: 0, left: 300, right: 1200, bottom: 700, width: 900, height: 690 }) as DOMRect;
    g.App = { currentScreen: 'terminal', returnToExistingTerminal: vi.fn(async () => showTerminal()) };
    g.API = { getSession: vi.fn(async () => ({ id: 'ses_a', tmux_session: 'cloude_a' })), adoptSession: vi.fn() };
    stop = initHomeInMain(document, () => {});
    document.getElementById('terminal-screen')!.classList.remove('active');
    document.getElementById('launchpad-screen')!.classList.add('active');
    (g.App as { currentScreen: string }).currentScreen = 'launchpad';
    ctrl = { _activeTmuxName: 'cloude_a', _pendingSelection: null, _closeAfterSwitch: vi.fn() };
    row = document.body.appendChild(document.createElement('div'));
    row.dataset.name = 'cloude_a';
    row.dataset.sessionId = 'ses_a';
});
afterEach(() => {
    stop();
    vi.unstubAllGlobals();
    document.body.replaceChildren();
    delete g.App;
    delete g.API;
});

describe('row click from Home in main-area mode', () => {
    it('an awake row opens the terminal and ends the mode', async () => {
        await Promise.resolve();
        expect(document.body.classList.contains(HOME_IN_MAIN_CLASS)).toBe(true);
        await activateRow(ctrl as never, row);
        await Promise.resolve();
        expect((g.App as { returnToExistingTerminal: unknown }).returnToExistingTerminal).toHaveBeenCalledOnce();
        expect(document.getElementById('launchpad-screen')!.classList.contains('active')).toBe(false);
        expect(document.body.classList.contains(HOME_IN_MAIN_CLASS)).toBe(false);
        expect(document.querySelector('.oc-surface')!.hasAttribute('inert')).toBe(false);
        expect(document.getElementById('terminal-screen')!.classList.contains('active')).toBe(true);
    });

    it('an asleep row does nothing from a plain click, as on master', async () => {
        row.dataset.asleep = '1';
        await activateRow(ctrl as never, row);
        expect((g.App as { returnToExistingTerminal: unknown }).returnToExistingTerminal).not.toHaveBeenCalled();
        expect((g.API as { getSession: unknown }).getSession).not.toHaveBeenCalled();
        expect(document.getElementById('launchpad-screen')!.classList.contains('active')).toBe(true);
    });
});
