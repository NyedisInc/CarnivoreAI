/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { replaceHashWith, rowsInScope } from './plugin-scope';
import type { CplugItem } from './cplugs-adapter';

const row = (id: string, tier: string, extra: Record<string, unknown> = {}): CplugItem => ({ id: `cplug:${id}`, cplugId: id, tier, name: id, ...extra }) as unknown as CplugItem;

describe('rowsInScope', () => {
    const rows = [row('a', 'builtin'), row('b', 'community'), row('c', 'dev')];
    it('the plugins scope unifies built-ins and store plugins while hiding dev unless developerMode is on', () => {
        const kept = rowsInScope(rows, { scope: 'plugins', developerMode: false, storeOnly: false }).map((r) => r.cplugId);
        expect(kept).toEqual(['a', 'b']);
        const devKept = rowsInScope(rows, { scope: 'plugins', developerMode: true, storeOnly: false }).map((r) => r.cplugId);
        expect(devKept).toEqual(['a', 'b', 'c']);
    });
    it('an unscoped page lists everything unless it is store-only', () => {
        expect(rowsInScope(rows, { scope: undefined, developerMode: false, storeOnly: false })).toHaveLength(3);
        expect(rowsInScope(rows, { scope: undefined, developerMode: false, storeOnly: true }).map((r) => r.cplugId)).toEqual(['b']);
    });
});

describe('replaceHashWith', () => {
    afterEach(() => { window.history.replaceState(null, '', '/'); });
    it('changes the address without adding a history entry, and tells the host with a hashchange', () => {
        const before = window.history.length;
        const heard = vi.fn();
        window.addEventListener('hashchange', heard);
        replaceHashWith('#settings/features/a');
        window.removeEventListener('hashchange', heard);
        expect(window.location.hash).toBe('#settings/features/a');
        expect(window.history.length).toBe(before);
        expect(heard).toHaveBeenCalledTimes(1);
    });
});
