/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { setViewClassSource } from './view-class';
import {
    FOLD_SLEEPING_KEY,
    init,
    isSleepFoldOpen,
    preferenceField,
    resetSleepFoldBands,
    setSleepingFolded,
    sleepingFolded,
    toggleSleepFoldBand,
    toggleSleepingFolded,
} from './sleep-fold.svelte';

beforeEach(() => {
    localStorage.clear();
    setDrawerEnv(null);
    setViewClassSource(() => 'desktop');
    resetSleepFoldBands();
    init();
});

describe('sleep-fold toggle (#3387, #3391)', () => {
    it('defaults to true (nested/folded) and maps desktop/mobile preference fields cleanly', () => {
        expect(sleepingFolded()).toBe(true);
        expect(preferenceField('desktop')).toBe('sidebar_fold_sleeping');
        expect(preferenceField('mobile')).toBe('sidebar_fold_sleeping_mobile');
    });

    it('toggles 2-state fold-sleeping, persists locally, and writes through PreferenceBridge', () => {
        const writes: Array<[string, boolean]> = [];
        const stored: Record<string, boolean> = {};
        setDrawerEnv({
            localStorage: window.localStorage,
            PreferenceBridge: {
                read: (field: string, fb: () => boolean | null) => (field in stored ? stored[field] : fb()),
                write: async (field: string, val: boolean, local: () => void) => {
                    writes.push([field, val]);
                    stored[field] = val;
                    local();
                },
            },
        });
        init();
        expect(sleepingFolded()).toBe(true);
        expect(toggleSleepingFolded()).toBe(false);
        expect(sleepingFolded()).toBe(false);
        expect(localStorage.getItem(FOLD_SLEEPING_KEY)).toBe('0');
        expect(writes).toEqual([['sidebar_fold_sleeping', false]]);

        setViewClassSource(() => 'mobile');
        init();
        expect(sleepingFolded()).toBe(false);
        expect(setSleepingFolded(true)).toBe(true);
        expect(writes).toEqual([['sidebar_fold_sleeping', false], ['sidebar_fold_sleeping_mobile', true]]);
    });

    it('tracks per-band inline open/closed state and resets when global fold turns off', () => {
        const repaint = vi.fn();
        setDrawerEnv({ SessionSidebar: { repaint } });
        setSleepingFolded(true);
        expect(isSleepFoldOpen('p:1')).toBe(false);
        expect(toggleSleepFoldBand('p:1')).toBe(true);
        expect(isSleepFoldOpen('p:1')).toBe(true);
        expect(isSleepFoldOpen('pinned')).toBe(false);

        setSleepingFolded(false);
        expect(isSleepFoldOpen('p:1')).toBe(false);
        expect(repaint).toHaveBeenCalled();
    });
});
