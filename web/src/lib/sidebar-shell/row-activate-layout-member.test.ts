/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from 'vitest';
import { activateRow } from './row-activate';
import type { RowController } from './row-globals';

const win = globalThis as unknown as Record<string, unknown>;

afterEach(() => {
    delete win.CloudeWeb;
    delete win.SessionSidebarLayouts;
    delete win.SessionSidebarBrowsers;
});

function memberRow(band: string): HTMLElement {
    const el = document.createElement('div');
    el.className = 'session-sidebar-row';
    el.dataset.name = 'cloude_b';
    el.dataset.sessionUuid = 'u-b';
    el.dataset.band = band;
    return el;
}

it('a member row under a Layout opens that Layout at the member and closes the drawer', async () => {
    const openLayout = vi.fn();
    const closed = vi.fn();
    win.CloudeWeb = { layoutPage: { openLayout } };
    const ctrl = { _rows: [{ name: 'cloude_b', session_uuid: 'u-b' }], _closeAfterSwitch: closed } as unknown as RowController;
    await activateRow(ctrl, memberRow('layout:L1'));
    expect(openLayout).toHaveBeenCalledWith('L1', 'u-b');
    expect(closed).toHaveBeenCalledTimes(1);
});

it('a reused tmux name cannot redirect a Layout click to another session', async () => {
    const openLayout = vi.fn();
    win.CloudeWeb = { layoutPage: { openLayout } };
    const ctrl = { _rows: [
        { name: 'cloude_b', session_uuid: 'older' },
        { name: 'cloude_b', session_uuid: 'u-b' },
    ] } as unknown as RowController;
    await activateRow(ctrl, memberRow('layout:L1'));
    expect(openLayout).toHaveBeenCalledWith('L1', 'u-b');
});

it('a row in any other band does not go to the Layout page', async () => {
    const openLayout = vi.fn();
    win.CloudeWeb = { layoutPage: { openLayout } };
    win.API = { getSession: async () => null };
    const ctrl = { _rows: [{ name: 'cloude_b', session_uuid: 'u-b' }], _activeTmuxName: 'cloude_b' } as unknown as RowController;
    await activateRow(ctrl, memberRow('terminals'));
    expect(openLayout).not.toHaveBeenCalled();
});
