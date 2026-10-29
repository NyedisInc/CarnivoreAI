/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { _resetForTest, defaultFor, DEFAULTS, iconVisible, init } from './row-icon-prefs';

afterEach(() => {
    _resetForTest();
    setDrawerEnv(null);
});

describe('iconVisible: no bridge at all', () => {
    it('falls back to the static defaults per density', () => {
        setDrawerEnv({});
        expect(iconVisible('compact', 'agents')).toBe(false);
        expect(iconVisible('compact', 'shells')).toBe(false);
        expect(iconVisible('compact', 'timers')).toBe(false);
        expect(iconVisible('cozy', 'agents')).toBe(true);
        expect(iconVisible('detailed', 'timers')).toBe(true);
    });

    it('an unknown density falls back to shown (the cozy/detailed default)', () => {
        setDrawerEnv({});
        expect(iconVisible('bogus', 'agents')).toBe(true);
    });
});

describe('iconVisible: a bridge with nothing stored', () => {
    it('reads the same static defaults as no bridge at all', () => {
        setDrawerEnv({ PreferenceBridge: { read: (_field: string, fallback: () => unknown) => fallback() } });
        expect(iconVisible('compact', 'agents')).toBe(false);
        expect(iconVisible('cozy', 'shells')).toBe(true);
    });
});

describe('iconVisible: a stored block', () => {
    function envWith(value: unknown) {
        return { PreferenceBridge: { read: () => value } };
    }

    it('an explicit override wins over the default', () => {
        setDrawerEnv(envWith({ compact: { agents: true } }));
        expect(iconVisible('compact', 'agents')).toBe(true);
    });

    it('a key missing from a present density still falls back to that icon\'s own default', () => {
        setDrawerEnv(envWith({ compact: { agents: true } }));
        expect(iconVisible('compact', 'shells')).toBe(false);
        expect(iconVisible('compact', 'timers')).toBe(false);
    });

    it('an explicit false in cozy/detailed overrides their shown default', () => {
        setDrawerEnv(envWith({ cozy: { shells: false } }));
        expect(iconVisible('cozy', 'shells')).toBe(false);
        expect(iconVisible('cozy', 'agents')).toBe(true);
    });

    it('a non-object stored value is treated as nothing stored', () => {
        setDrawerEnv(envWith('garbage'));
        expect(iconVisible('compact', 'agents')).toBe(false);
    });
});

describe('DEFAULTS table', () => {
    it('is compact off, cozy and detailed on', () => {
        expect(DEFAULTS).toEqual({ compact: false, cozy: true, detailed: true });
    });
});

describe('the three extra toggles (cup, pin, menu), issue #1061 follow-up', () => {
    it('default() answers true for cup/pin/menu at every density, including compact', () => {
        expect(defaultFor('compact', 'cup')).toBe(true);
        expect(defaultFor('compact', 'pin')).toBe(true);
        expect(defaultFor('compact', 'menu')).toBe(true);
        expect(defaultFor('cozy', 'cup')).toBe(true);
        expect(defaultFor('detailed', 'menu')).toBe(true);
    });

    it('iconVisible reads the same always-shown default with no bridge', () => {
        setDrawerEnv({});
        expect(iconVisible('compact', 'cup')).toBe(true);
        expect(iconVisible('compact', 'pin')).toBe(true);
        expect(iconVisible('compact', 'menu')).toBe(true);
    });

    it('an explicit false on one extra toggle does not disturb the other two', () => {
        setDrawerEnv({ PreferenceBridge: { read: () => ({ compact: { menu: false } }) } });
        expect(iconVisible('compact', 'menu')).toBe(false);
        expect(iconVisible('compact', 'cup')).toBe(true);
        expect(iconVisible('compact', 'pin')).toBe(true);
    });

    it('does not disturb the original three, which keep their own density defaults', () => {
        expect(defaultFor('compact', 'agents')).toBe(false);
        expect(defaultFor('cozy', 'shells')).toBe(true);
    });
});

describe('init(): following a live change', () => {
    it('repaints the drawer when the preference changes elsewhere', () => {
        let follow: ((value: unknown) => void) | null = null;
        const repaint = vi.fn();
        setDrawerEnv({
            PreferenceBridge: {
                read: () => null,
                follow: (_field: string, apply: (value: unknown) => void) => {
                    follow = apply;
                    return () => { follow = null; };
                },
            },
            SessionSidebar: { repaint },
        });
        init();
        expect(follow).not.toBeNull();
        follow!({ compact: { agents: true } });
        expect(repaint).toHaveBeenCalledTimes(1);
    });

    it('is idempotent: a second call does not double-subscribe', () => {
        let followCount = 0;
        setDrawerEnv({
            PreferenceBridge: {
                read: () => null,
                follow: () => { followCount += 1; return () => {}; },
            },
        });
        init();
        init();
        expect(followCount).toBe(1);
    });
});

describe('the carnivore timers icon (huddle item 454, shown by default since #1639)', () => {
    it('is shown at every density until a stored false hides it', () => {
        setDrawerEnv({});
        expect(defaultFor('compact', 'automations')).toBe(true);
        expect(defaultFor('cozy', 'automations')).toBe(true);
        expect(iconVisible('detailed', 'automations')).toBe(true);
        setDrawerEnv({ PreferenceBridge: { read: () => ({ cozy: { automations: false } }) } });
        expect(iconVisible('cozy', 'automations')).toBe(false);
        expect(iconVisible('compact', 'automations')).toBe(true);
    });
});
