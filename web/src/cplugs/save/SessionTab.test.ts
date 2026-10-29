/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import SessionTab from './SessionTab.svelte';
import { saveCplug } from './index';
import { cplugPlugins } from '../host/readers';
import { cplugEnablement } from '../host/enablement.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import type { PointsApi, RestoreResult } from './points-api';

setLocale('en');

const POINT = { id: 'p1', takenAt: '2026-10-01T10:00:00Z', reason: 'kill', turns: 4, sizeBytes: 1048576, rawBytes: 4194304, pinned: false, failsafe: false, digest: null };
const STORE = { usedBytes: 1073741824, capBytes: 4294967296, pointCount: 1, pinnedCount: 0, keep: 10, bySession: null };

function fakeApi(restored: RestoreResult | { error: string }): PointsApi {
    return {
        summary: vi.fn(async () => ({ kind: 'ok' as const, value: STORE })),
        points: vi.fn(async () => ({ kind: 'ok' as const, value: { points: [POINT], digest: null } })),
        pin: vi.fn(async () => ({ kind: 'ok' as const, value: null })),
        restore: vi.fn(async () => ('error' in restored ? { kind: 'error' as const, message: restored.error } : { kind: 'ok' as const, value: restored })),
    };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

const mounted: Array<Record<string, unknown>> = [];
async function open(api: PointsApi): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(SessionTab, { target, props: { session: { session_uuid: 'u1' }, api } }));
    await settle();
    return target;
}

afterEach(() => {
    for (const m of mounted.splice(0)) unmount(m);
    document.body.innerHTML = '';
    cplugEnablement.enabled = {};
});

describe('the restore points tab', () => {
    test('loads this session\'s points from the plugin calls and draws the table', async () => {
        const api = fakeApi({ transcriptStatus: 'written', sessionStatus: 'started', sessionCode: '', sessionUuid: 'u1', detail: '' });
        const root = await open(api);
        expect(api.points).toHaveBeenCalledWith('u1');
        expect(root.querySelector('[data-point-id="p1"]')).not.toBeNull();
        expect(root.querySelector('[data-restore="summary"]')).toBeNull();
    });

    test('a pin goes to the pin call and says so', async () => {
        const api = fakeApi({ transcriptStatus: 'written', sessionStatus: 'started', sessionCode: '', sessionUuid: 'u1', detail: '' });
        const root = await open(api);
        root.querySelector<HTMLElement>('[data-pin]')!.click();
        await settle();
        expect(api.pin).toHaveBeenCalledWith('u1', 'p1', true);
        expect(root.querySelector('[data-rpt-notice]')!.textContent).toContain('pinned');
    });

    test('a restore that started a session says so', async () => {
        const api = fakeApi({ transcriptStatus: 'written', sessionStatus: 'started', sessionCode: '', sessionUuid: 'u1', detail: '' });
        const root = await open(api);
        root.querySelector<HTMLElement>('[data-restore="exact"]')!.click();
        await settle();
        expect(api.restore).toHaveBeenCalledWith('u1', 'p1');
        expect(root.querySelector('[data-rpt-notice]')!.textContent).toContain('a session is resuming it');
    });

    test('a missing start grant shows the server\'s sentence plainly', async () => {
        const sentence = 'the transcript is restored. starting its session needs the sessions.read and sessions.create permissions; grant them to restore points on the plugins page';
        const api = fakeApi({ transcriptStatus: 'written', sessionStatus: 'refused', sessionCode: 'grant_needed', sessionUuid: 'u1', detail: sentence });
        const root = await open(api);
        root.querySelector<HTMLElement>('[data-restore="exact"]')!.click();
        await settle();
        expect(root.querySelector('[data-rpt-notice]')!.textContent).toBe(sentence);
    });

    test('a refused restore shows the server\'s words', async () => {
        const root = await open(fakeApi({ error: 'a transcript for this conversation already exists' }));
        root.querySelector<HTMLElement>('[data-restore="exact"]')!.click();
        await settle();
        expect(root.querySelector('[data-rpt-notice]')!.textContent).toBe('a transcript for this conversation already exists');
    });
});

describe('the contributions', () => {
    test('the settings panel and the session tab are enabled only while save is on', () => {
        const contributions = cplugPlugins([saveCplug])[0]!.contributions;
        expect(contributions.map((c) => c.surface).sort()).toEqual(['session-tab', 'settings-panel']);
        const ctx = { flags: {}, refresh: () => undefined };
        cplugEnablement.enabled = { save: false };
        expect(contributions.some((c) => c.enabled(ctx))).toBe(false);
        cplugEnablement.enabled = { save: true };
        expect(contributions.every((c) => c.enabled(ctx))).toBe(true);
    });

    test('it ships off by default, so a fresh install shows neither', () => {
        cplugEnablement.enabled = {};
        const ctx = { flags: {}, refresh: () => undefined };
        expect(cplugPlugins([saveCplug])[0]!.contributions.some((c) => c.enabled(ctx))).toBe(false);
    });
});
