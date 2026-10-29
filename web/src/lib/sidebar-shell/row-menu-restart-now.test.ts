/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { flushSync } from 'svelte';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { rowMenuItems } from '../item-menu/menus/row';
import { contextFromTrigger } from '../item-menu/row-context';
import { closeRowMenu, installRowMenuOpener, openRowMenuFromTrigger } from '../item-menu/row-open';
import { drawList, loadLegacyDrawer, resetDrawer, type LegacyWindow } from './legacy-fixture';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

const EXTRA = [
    'session-key.js', 'session-restart-live.js', 'session-restart-options.js',
    'session-restart-picker.js', 'session-restart-direct.js',
];

const PANEL = '#session-row-menu-panel';

let win: LegacyWindow;
const NAME = 'cloude_alive';

beforeAll(() => {
    const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
    proto.showPopover ??= function () {};
    proto.hidePopover ??= function () {};
    win = loadLegacyDrawer();
    installRowMenuOpener();
    const g = globalThis as LegacyWindow;
    if (!g.CSS || typeof g.CSS.escape !== 'function') g.CSS = { ...(g.CSS || {}), escape: (v: string) => String(v) };
    resetDrawer();
    const log = console.log;
    console.log = () => {};
    try {
        for (const f of EXTRA) new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', f), 'utf8'))();
    } finally {
        console.log = log;
    }
    win.SessionSidebar = { _closeAfterSwitch: vi.fn(), _fetchAndRender: vi.fn(async () => {}) };
    win.SessionRestartReturn = { reopen: vi.fn(async () => ({ status: 'reopened' })) };
    drawList([{ name: NAME, created_by_cloude: true, status: 'idle', is_active: true, project_id: null }]);
});

afterEach(() => {
    closeRowMenu();
    flushSync();
    document.querySelectorAll('.restart-picker').forEach((el) => el.remove());
    setShift(false);
});

function setShift(down: boolean): void {
    window.dispatchEvent(new KeyboardEvent(down ? 'keydown' : 'keyup', { key: 'Shift', shiftKey: down }));
    flushSync();
}

function trigger(): Element {
    const el = document.querySelector(`[data-row-menu="${NAME}"]`);
    expect(el, 'setup: the live row must paint a menu trigger').toBeTruthy();
    return el as Element;
}

function openMenu(): void {
    openRowMenuFromTrigger(trigger());
    flushSync();
}

function panelIds(): string[] {
    return [...document.querySelectorAll(`${PANEL} [data-node]`)].map((el) => el.getAttribute('data-node') || '');
}

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

function stubApi(preview: Record<string, unknown>) {
    const respawnSession = vi.fn(async () => ({ ok: true, name: NAME, session_id: 'ses_1' }));
    win.API = {
        restartPreview: vi.fn(async () => preview),
        recreatePreview: vi.fn(async () => { throw new Error('not asked'); }),
        respawnSession,
    };
    return respawnSession;
}

const ALIVE = { pane_state: 'alive', unchanged: { kind: 'not_dead', actionable: false }, projected: { kind: 'agent' }, options: [] };

describe('shift-held restart now', () => {
    it('without shift the menu is unchanged', () => {
        const expected = rowMenuItems(contextFromTrigger(trigger())!).map((i) => i.id);
        openMenu();
        expect(panelIds()).toEqual(expected);
        expect(panelIds()).not.toContain('restart-now');
        expect(panelIds()).toContain('restart');
    });

    it('with shift the item is first, styled like update, labelled, and follows the key live', () => {
        setShift(true);
        openMenu();
        expect(panelIds()[0]).toBe('restart-now');
        const item = document.querySelector(`${PANEL} [data-node="restart-now"]`) as HTMLElement;
        expect(item.classList.contains('acm-item--update')).toBe(true);
        expect(item.textContent).toContain('restart now (kills and resumes)');
        expect(item.getAttribute('aria-disabled')).not.toBe('true');
        setShift(false);
        expect(panelIds()).not.toContain('restart-now');
        setShift(true);
        expect(panelIds()).toContain('restart-now');
    });

    it('a click on a measured-live row posts the kill with confirm_restart_live and no picker', async () => {
        const respawn = stubApi(ALIVE);
        setShift(true);
        openMenu();
        (document.querySelector(`${PANEL} [data-node="restart-now"]`) as HTMLElement).click();
        await settle();
        expect(respawn).toHaveBeenCalledTimes(1);
        expect(respawn).toHaveBeenCalledWith(NAME, null, true, undefined);
        expect(document.querySelector('.restart-picker')).toBeNull();
    });

    it('a pane that was not measured opens the normal picker, unarmed, and posts nothing', async () => {
        const respawn = stubApi({ pane_state: 'unknown', unchanged: { kind: 'not_dead' }, projected: { kind: 'agent' }, options: [] });
        setShift(true);
        openMenu();
        (document.querySelector(`${PANEL} [data-node="restart-now"]`) as HTMLElement).click();
        await settle();
        expect(respawn).not.toHaveBeenCalled();
        const picker = document.querySelector('.restart-picker');
        expect(picker, 'the normal picker must open').toBeTruthy();
        expect(picker!.querySelector('[data-restart-now-fallback]')!.textContent)
            .toBe('not restarted at once: the pane was not measured running');
        const arm = picker!.querySelector('#restart-picker-live') as HTMLInputElement | null;
        expect(arm === null || arm.checked === false).toBe(true);
    });

    it('a live pane whose outcome is not actionable falls back with the arm box unticked', async () => {
        const respawn = stubApi({ ...ALIVE, projected: { kind: 'transcript_missing' } });
        setShift(true);
        openMenu();
        (document.querySelector(`${PANEL} [data-node="restart-now"]`) as HTMLElement).click();
        await settle();
        expect(respawn).not.toHaveBeenCalled();
        const arm = document.querySelector('#restart-picker-live') as HTMLInputElement;
        expect(arm).toBeTruthy();
        expect(arm.checked).toBe(false);
    });
});
