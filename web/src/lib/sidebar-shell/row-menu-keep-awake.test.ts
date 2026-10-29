/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROW_ITEMS } from '../item-menu/menus/row-items';
import type { RowMenuCtx } from '../item-menu/row-context';

type Ctx = Record<string, unknown>;
type Item = { id: string; label: (c: RowMenuCtx) => string; available: (c: RowMenuCtx) => boolean };
const g = globalThis as unknown as Record<string, any>;

const ROW_MENU_ACTIONS_SCRIPT = import.meta.glob('../../../../client/js/session-row-menu-actions.js');

const ctx = (over: Ctx = {}): RowMenuCtx => ({ name: 'cloude_a', kind: 'session', hostKey: 'local', agentFamily: 'claude', ...over } as unknown as RowMenuCtx);

describe('row menu keep awake item', () => {
    let item: Item;
    let run: (id: string, c: RowMenuCtx) => Promise<void>;
    let store: { isKeptAwake: ReturnType<typeof vi.fn>; setKeepAwake: ReturnType<typeof vi.fn> };

    beforeAll(async () => {
        g.window = globalThis;
        g.CloudeI18n = { t: (k: string) => k };
        for (const load of Object.values(ROW_MENU_ACTIONS_SCRIPT)) await load();
        item = ROW_ITEMS.find((i) => i.id === 'keep-awake') as unknown as Item;
        run = g.SessionRowMenuActions.run;
    });
    beforeEach(() => {
        store = { isKeptAwake: vi.fn(), setKeepAwake: vi.fn(async () => {}) };
        g.CloudeWeb = { autoSleep: store };
    });

    it('offers turn on while off, and calls the route with keep_awake true', async () => {
        store.isKeptAwake.mockReturnValue(false);
        expect(item.available(ctx())).toBe(true);
        expect(item.label(ctx())).toBe('session.menu.keep_awake.turn_on');
        await run('keep-awake', ctx());
        expect(store.setKeepAwake).toHaveBeenCalledWith('cloude_a', true);
    });

    it('shows turn off while on, and flips it off', async () => {
        store.isKeptAwake.mockReturnValue(true);
        expect(item.label(ctx())).toBe('session.menu.keep_awake.turn_off');
        await run('keep-awake', ctx());
        expect(store.setKeepAwake).toHaveBeenCalledWith('cloude_a', false);
    });

    it('stays hidden before the state is read, on remote and browser rows, and for non-sleepable families; an asleep row offers it (#1839)', () => {
        store.isKeptAwake.mockReturnValue(null);
        expect(item.available(ctx())).toBe(false);
        store.isKeptAwake.mockReturnValue(false);
        expect(item.available(ctx({ hostKey: 'peer-x' }))).toBe(false);
        expect(item.available(ctx({ asleep: true }))).toBe(true);
        expect(item.available(ctx({ kind: 'browser' }))).toBe(false);
        expect(item.available(ctx({ agentFamily: '' }))).toBe(false);
    });
});
