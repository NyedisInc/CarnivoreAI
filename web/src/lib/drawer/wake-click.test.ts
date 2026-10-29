/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
// The menu's wake run is the sleep module's real one (it calls the server); these cases stand in for it and record how it is called.
const wake = vi.hoisted(() => ({ run: async (_ctx: unknown): Promise<boolean> => false }));
vi.mock('./row-menu-sleep', async (orig) => ({
    ...(await orig<typeof import('./row-menu-sleep')>()), runWake: (ctx: unknown) => wake.run(ctx),
}));
import { onAsleepClick } from './wake-click';

type Win = Record<string, unknown>;
const win = window as unknown as Win;
let gen = 0;
let ctrl: Record<string, any>;

function rowEl(name: string, asleep: boolean, uuid = 'u-a'): HTMLElement {
    const el = document.createElement('div');
    el.className = 'session-sidebar-row';
    el.dataset.name = name;
    el.dataset.sessionUuid = uuid;
    if (asleep) el.dataset.asleep = '1';
    document.body.append(el);
    return el;
}

beforeEach(() => {
    gen = 0;
    document.body.innerHTML = '';
    ctrl = { _rows: [{ name: 'carnivore_a', asleep: true, session_uuid: 'u-a', label: 'a' }] };
    win.NavigationGeneration = { begin: () => ++gen, isCurrent: (t: unknown) => t === gen, keep: (t: unknown) => t === gen };
});
afterEach(() => { delete win.NavigationGeneration; wake.run = async () => false; });

describe('onAsleepClick', () => {
    it('cannot wake a row the controller does not list: answers false, opens nothing', async () => {
        const open = vi.fn();
        ctrl._rows = [];
        expect(await onAsleepClick(ctrl, rowEl('carnivore_a', true), open)).toBe(false);
        expect(open).not.toHaveBeenCalled();
    });

    it('does not match a row that only shares the tmux name (a recreate reuses names)', async () => {
        const open = vi.fn();
        expect(await onAsleepClick(ctrl, rowEl('carnivore_a', true, 'u-other'), open)).toBe(false);
        expect(open).not.toHaveBeenCalled();
    });

    it('wakes by session_uuid, then opens the live row the controller now lists', async () => {
        const runWake = vi.fn(async () => {
            ctrl._rows = [{ name: 'carnivore_a', asleep: false, session_uuid: 'u-a' }];
            return true;
        });
        wake.run = runWake;
        const asleep = rowEl('carnivore_a', true);
        asleep.remove();
        const live = rowEl('carnivore_a', false);
        const open = vi.fn(async () => {});
        expect(await onAsleepClick(ctrl, asleep, open)).toBe(true);
        expect(runWake).toHaveBeenCalledWith({ name: 'carnivore_a', label: 'a', sessionUuid: 'u-a', surface: 'sidebar' });
        expect(open).toHaveBeenCalledWith(ctrl, live);
    });

    it('a refused wake opens nothing', async () => {
        wake.run = async () => false;
        const open = vi.fn();
        expect(await onAsleepClick(ctrl, rowEl('carnivore_a', true), open)).toBe(true);
        expect(open).not.toHaveBeenCalled();
    });

    it('a navigation during the wake is not overridden', async () => {
        wake.run = async () => {
            gen += 1;
            ctrl._rows = [{ name: 'carnivore_a', asleep: false, session_uuid: 'u-a' }];
            return true;
        };
        const asleep = rowEl('carnivore_a', true);
        asleep.remove();
        rowEl('carnivore_a', false);
        const open = vi.fn();
        await onAsleepClick(ctrl, asleep, open);
        expect(open).not.toHaveBeenCalled();
    });

    it('a double click wakes once', async () => {
        let release: () => void = () => {};
        const gate = new Promise<void>((r) => { release = r; });
        const runWake = vi.fn(async () => { await gate; return true; });
        wake.run = runWake;
        const el = rowEl('carnivore_a', true);
        const first = onAsleepClick(ctrl, el);
        const second = onAsleepClick(ctrl, el);
        release();
        await Promise.all([first, second]);
        expect(runWake).toHaveBeenCalledTimes(1);
    });
});
