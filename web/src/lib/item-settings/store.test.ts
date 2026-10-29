/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const served = vi.hoisted(() => ({
    document: { status: 'ok', revision: 0, items: { widget: {}, plugin: {} } } as Record<string, unknown>,
    reads: 0,
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (path: string) => {
            if (path !== '/item-settings') throw new real.ApiError('not in this test', 404);
            served.reads += 1;
            return structuredClone(served.document);
        },
    };
});

import { isWidgetDisabled, itemSettings, widgetSetting, ITEM_SETTINGS_CHANGED_FRAME } from './store.svelte';
import { startEvents, stop } from '../../opscenter/api/events.svelte';
import { homeLayout } from '../../opscenter/engine/layout.svelte';
import { auth } from '../../opscenter/api/auth.svelte';

async function serve(revision: number, widget: Record<string, unknown>): Promise<void> {
    served.document = { status: 'ok', revision, items: { widget, plugin: {} } };
    await itemSettings.refresh(true);
}

beforeEach(async () => {
    auth.state = 'signed-in';
    await serve(0, {});
});

describe('reading a setting', () => {
    test('the manifest default until someone chooses, then the stored choice', async () => {
        expect(widgetSetting('core.activity-log', 'showSystem')).toBe(true);
        await serve(1, { 'core.activity-log': { values: { showSystem: false }, revision: 1 } });
        expect(widgetSetting('core.activity-log', 'showSystem')).toBe(false);
    });

    test('a stored value that does not fit falls back to the default', async () => {
        await serve(1, { 'core.activity-log': { values: { showSystem: 'no' }, revision: 1 } });
        expect(widgetSetting('core.activity-log', 'showSystem')).toBe(true);
    });

    test('an undeclared key is a programming error, not a state', () => {
        expect(() => widgetSetting('core.notes', 'wrap')).toThrow();
    });
});

describe('a switched-off widget', () => {
    test('is on until the server says off, then no add list offers it', async () => {
        homeLayout.resetAll();
        homeLayout.hide('notes');
        const offered = () => homeLayout.hiddenCells().map((meta) => meta.id);
        expect(isWidgetDisabled('core.notes')).toBe(false);
        expect(offered()).toContain('notes');
        await serve(1, { 'core.notes': { enabled: false, revision: 1 } });
        expect(isWidgetDisabled('core.notes')).toBe(true);
        expect(offered()).not.toContain('notes');
        await serve(2, { 'core.notes': { enabled: true, revision: 2 } });
        expect(offered()).toContain('notes');
    });
});

describe('the changed frame', () => {
    test('re-reads only for a higher revision', async () => {
        let emit: (frame: Record<string, unknown>) => void = () => {};
        (globalThis as { AppEvents?: unknown }).AppEvents = {
            subscribe: (handler: (frame: Record<string, unknown>) => void) => {
                emit = handler;
                return () => {};
            },
            isConnected: () => true,
        };
        startEvents();
        await serve(5, {});
        const before = served.reads;
        emit({ type: ITEM_SETTINGS_CHANGED_FRAME, revision: 5 });
        emit({ type: ITEM_SETTINGS_CHANGED_FRAME, revision: 3 });
        await Promise.resolve();
        expect(served.reads).toBe(before);
        emit({ type: ITEM_SETTINGS_CHANGED_FRAME, revision: 6 });
        await vi.waitFor(() => expect(served.reads).toBe(before + 1));
        stop();
    });
});
