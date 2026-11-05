/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { featureHandOffFragment, replaceHashWith, rowsInScope } from './plugin-scope';
import type { CplugItem } from './cplugs-adapter';
import { settingsFeatureFragment, settingsPluginFragment } from '../settings-page/settings-hash';

const row = (id: string, tier: string, extra: Record<string, unknown> = {}): CplugItem => ({ id: `cplug:${id}`, cplugId: id, tier, name: id, ...extra }) as unknown as CplugItem;

describe('rowsInScope', () => {
    const rows = [row('a', 'builtin'), row('b', 'community')];
    it('the plugins scope lists no compiled-in tier', () => {
        const kept = rowsInScope(rows, { scope: 'plugins', developerMode: false, storeOnly: false }).map((r) => r.cplugId);
        expect(kept).not.toContain('a');
        expect(kept).toContain('b');
    });
    it('an unscoped page lists everything unless it is store-only', () => {
        expect(rowsInScope(rows, { scope: undefined, developerMode: false, storeOnly: false })).toHaveLength(2);
        expect(rowsInScope(rows, { scope: undefined, developerMode: false, storeOnly: true }).map((r) => r.cplugId)).toEqual(['b']);
    });
});

describe('featureHandOffFragment', () => {
    it('lands on the features overview row when the link did not ask for settings', () => {
        expect(featureHandOffFragment(row('a', 'builtin', { enabled: true }), false)).toBe(settingsFeatureFragment('a'));
    });
    it('lands on the features overview row when the feature is off, even if the link asked for settings', () => {
        expect(featureHandOffFragment(row('a', 'builtin', { enabled: false }), true)).toBe(settingsFeatureFragment('a'));
    });
    it('opens the feature entry in the rail when it is on, has settings and the link asked for them', () => {
        const withSettings = row('a', 'builtin', { enabled: true, state: 'active', settingsSchema: { fields: [] } });
        expect(featureHandOffFragment(withSettings, true)).toBe(settingsPluginFragment('a'));
    });
    it('a feature with no settings lands on the overview even when the link asked for them', () => {
        expect(featureHandOffFragment(row('a', 'builtin', { enabled: true, state: 'active', settingsSchema: null }), true)).toBe(settingsFeatureFragment('a'));
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
