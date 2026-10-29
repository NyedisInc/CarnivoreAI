/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runRestart } from './restart-click';

const win = window as unknown as Record<string, any>;
const KEYS = ['Router', 'SessionRestartPicker', 'SessionRestartReturn', 'SessionKey', 'API', 'Launchpad'];
let shown: string[];
let ctrl: { _lastSig: string | null; _fetchAndRender: ReturnType<typeof vi.fn>; _closeAfterSwitch: ReturnType<typeof vi.fn> };

beforeEach(() => {
    shown = [];
    ctrl = { _lastSig: 'sig', _fetchAndRender: vi.fn(async () => {}), _closeAfterSwitch: vi.fn() };
    win.Router = { showError: (m: string) => shown.push(m) };
    vi.spyOn(console, 'error').mockImplementation(() => {});
    if (!win.CSS?.escape) win.CSS = { escape: (v: string) => v };
});
afterEach(() => { for (const k of KEYS) delete win[k]; vi.restoreAllMocks(); });

describe('runRestart', () => {
    it('a missing picker is reported on the banner, never alert()', async () => {
        win.alert = () => { throw new Error('native alert() must not be used'); };
        await runRestart(ctrl as never, 'demo', null, 'local');
        expect(shown).toEqual(['could not restart "demo": the restart picker did not load.']);
    });

    it('a cancelled picker with no error does nothing', async () => {
        win.SessionRestartPicker = { open: async () => null, lastError: () => null };
        await runRestart(ctrl as never, 'demo', null, 'local');
        expect(shown).toEqual([]);
        expect(ctrl._fetchAndRender).not.toHaveBeenCalled();
    });

    it('a refused respawn is reported and the drawer is re-read', async () => {
        win.SessionRestartPicker = { open: async () => ({ mode: 'restart', agentType: 'claude' }), lastError: () => null };
        win.API = { respawnSession: async () => ({ ok: false, detail: 'pane busy' }) };
        await runRestart(ctrl as never, 'demo', null, 'local');
        expect(shown[0]).toContain('pane busy');
        expect(ctrl._lastSig).toBeNull();
        expect(ctrl._fetchAndRender).toHaveBeenCalledTimes(1);
    });

    it('a successful restart that reopens closes the overlay and does not re-read', async () => {
        win.SessionRestartPicker = { open: async () => ({ mode: 'restart' }), lastError: () => null };
        win.API = { respawnSession: async () => ({ ok: true }) };
        win.SessionRestartReturn = { reopen: async () => ({ status: 'reopened' }) };
        await runRestart(ctrl as never, 'demo', null, 'local');
        expect(ctrl._closeAfterSwitch).toHaveBeenCalledTimes(1);
        expect(ctrl._fetchAndRender).not.toHaveBeenCalled();
    });

    it('the status comes off the kebab trigger, not the row', async () => {
        const open = vi.fn(async (..._args: unknown[]) => null);
        win.SessionRestartPicker = { open, lastError: () => null };
        const row = document.createElement('div');
        row.innerHTML = '<button data-row-menu="demo" data-row-menu-status="idle" data-row-menu-host-key="local"></button>';
        await runRestart(ctrl as never, 'demo', row, undefined);
        expect(open.mock.calls[0]?.[2]).toBe('idle');
    });
});
