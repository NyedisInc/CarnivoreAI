/** @vitest-environment jsdom */
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, test } from 'vitest';
import { setLocale } from '../../lib/i18n/index.svelte';
import { ApiError } from '../sdk';
import FolderUnits from './FolderUnits.svelte';
import { agoText } from './folders-api';
import type { Fetcher } from './folders-api';

setLocale('en');

const NOW = Date.parse('2026-10-18T13:00:00Z');
const UNIT = {
    unit: 'reviewboard.boards',
    plugin: 'reviewboard',
    data_id: 'boards',
    plugin_name_key: 'cplug.reviewboard.name',
    root: '/state/review-boards/boards',
    marked: true,
    backup_on: true,
    points: 2,
    bytes: 3 * 1024 * 1024,
    last_point_at: '2026-10-18T10:00:00Z',
};
const POINTS = [
    { point_id: '20261018T100000Z-follow', created_at: '2026-10-18T10:00:00Z', files: 4, bytes: 3 * 1024 * 1024 },
    { point_id: '20261017T100000Z-follow', created_at: '2026-10-17T10:00:00Z', files: 3, bytes: 2 * 1024 * 1024 },
];

interface Call {
    path: string;
    method: string;
    body: Record<string, unknown> | null;
}

function harness(units: readonly unknown[] = [UNIT], fail = false) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        if (call.method === 'POST') {
            if (fail) throw new ApiError('boom', 409, 'restore_failed', { detail: { code: 'restore_failed', detail: 'a chunk is damaged' } });
            return { unit: UNIT.unit, point_id: call.body!.point_id, target: '/state/review-boards/boards.restored-older', written: 3, bytes: 10 };
        }
        if (call.method === 'PUT') return {};
        if (path === '/cplugs/save') return { revision: 7, settings: { vaultFolderOptOut: 'gone.plugin' } };
        return path.endsWith('/points') ? { unit: UNIT.unit, points: POINTS } : { folders: units };
    }) as unknown as Fetcher;
    return { fetcher, calls };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) await tick();
    flushSync();
}

let target: HTMLElement;
let panel: Record<string, unknown> | null = null;
afterEach(() => {
    if (panel) unmount(panel);
    panel = null;
    target?.remove();
});

async function render(fetcher: Fetcher): Promise<HTMLElement> {
    target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(FolderUnits, { target, props: { fetcher, now: () => NOW } });
    await settle();
    return target;
}

describe('plugin folders region', () => {
    test('one row per folder unit with the plugin name, size, restore points and a relative last backup', async () => {
        const el = await render(harness().fetcher);
        const rows = el.querySelectorAll('[data-tm="folder"]');
        expect(rows).toHaveLength(1);
        expect(rows[0]!.querySelector('[data-tm="folder-name"]')?.textContent).toBe('review board / boards');
        const meta = rows[0]!.querySelector('[data-tm="folder-meta"]')?.textContent ?? '';
        expect(meta).toContain('3.0 mb');
        expect(meta).toContain('restore points: 2');
        expect(meta).toContain('last backup 3h ago');
        expect(rows[0]!.querySelector('[data-tm="folder-restore"]')).not.toBeNull();
    });

    test('every marked folder gets a switch from the list, and a folder no plugin marks gets none', async () => {
        const marked = { ...UNIT, unit: 'flow.graph', plugin: 'flow', data_id: 'graph', plugin_name_key: '', backup_on: false, points: 0, last_point_at: null };
        const gone = { ...UNIT, unit: 'old.thing', plugin: 'old', data_id: 'thing', plugin_name_key: '', marked: false, backup_on: false };
        const el = await render(harness([UNIT, marked, gone]).fetcher);
        const rows = [...el.querySelectorAll('[data-tm="folder"]')];
        const switchOf = (unit: string) => rows.find((r) => r.getAttribute('data-unit') === unit)!.querySelector('[data-tm="folder-switch"]');
        expect(switchOf('reviewboard.boards')?.getAttribute('aria-checked')).toBe('true');
        expect(switchOf('flow.graph')?.getAttribute('aria-checked')).toBe('false');
        expect(switchOf('old.thing')).toBeNull();
        expect(rows.find((r) => r.getAttribute('data-unit') === 'flow.graph')!.querySelector('[data-tm="folder-off"]')?.textContent).toContain('no new backups');
        expect(rows.find((r) => r.getAttribute('data-unit') === 'reviewboard.boards')!.querySelector('[data-tm="folder-off"]')).toBeNull();
    });

    test('flipping a switch writes only that folder into the opted-out setting and keeps the other entries', async () => {
        const { fetcher, calls } = harness();
        const el = await render(fetcher);
        el.querySelector<HTMLButtonElement>('[data-tm="folder-switch"]')!.click();
        await settle();
        const put = calls.find((c) => c.method === 'PUT')!;
        expect(put.path).toBe('/cplugs/save');
        expect(put.body).toEqual({ revision: 7, settings: { vaultFolderOptOut: 'gone.plugin,reviewboard.boards' } });
        expect(calls.filter((c) => c.path === '/cplugs/save/folders').length).toBe(2);
    });

    test('says so in one line when there are no plugin folders', async () => {
        const el = await render(harness([]).fetcher);
        expect(el.querySelector('[data-tm="folders-empty"]')?.textContent).toBe('no plugin folders are backed up yet.');
        expect(el.querySelector('[data-tm="folder"]')).toBeNull();
    });

    test('restore asks first, posts the chosen point and names the new folder', async () => {
        const { fetcher, calls } = harness();
        const el = await render(fetcher);
        el.querySelector<HTMLButtonElement>('[data-tm="folder-restore"]')!.click();
        await settle();
        expect(calls.some((c) => c.method === 'POST')).toBe(false);
        const select = el.querySelector<HTMLSelectElement>('[data-tm="folder-point"]')!;
        expect(select.options).toHaveLength(2);
        select.value = POINTS[1]!.point_id;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        flushSync();
        el.querySelector<HTMLButtonElement>('[data-tm="folder-confirm-go"]')!.click();
        await settle();
        const post = calls.find((c) => c.method === 'POST')!;
        expect(post.path).toBe('/cplugs/save/folders/reviewboard.boards/restore');
        expect(post.body).toEqual({ point_id: POINTS[1]!.point_id });
        expect(el.querySelector('[data-tm="folders-note"]')?.textContent).toContain('/state/review-boards/boards.restored-older');
        expect(el.querySelector('[data-tm="folder-confirm"]')).toBeNull();
    });

    test('cancel writes nothing, and a refused restore shows the server reason and no new folder', async () => {
        const first = harness();
        let el = await render(first.fetcher);
        el.querySelector<HTMLButtonElement>('[data-tm="folder-restore"]')!.click();
        await settle();
        el.querySelector<HTMLButtonElement>('[data-tm="folder-cancel"]')!.click();
        await settle();
        expect(first.calls.some((c) => c.method === 'POST')).toBe(false);
        expect(el.querySelector('[data-tm="folder-confirm"]')).toBeNull();
        unmount(panel!);
        panel = null;
        target.remove();
        el = await render(harness([UNIT], true).fetcher);
        el.querySelector<HTMLButtonElement>('[data-tm="folder-restore"]')!.click();
        await settle();
        el.querySelector<HTMLButtonElement>('[data-tm="folder-confirm-go"]')!.click();
        await settle();
        expect(el.querySelector('[data-tm="folders-problem"]')?.textContent).toContain('a chunk is damaged');
        expect(el.querySelector('[data-tm="folders-note"]')).toBeNull();
    });
});

describe('agoText', () => {
    const t = (key: string, params?: Record<string, unknown>): string => `${key}:${params?.count ?? ''}`;
    test('picks days, hours, minutes, just now and never', () => {
        const at = (secondsAgo: number): string => new Date(NOW - secondsAgo * 1000).toISOString();
        expect(agoText(at(2 * 86_400 + 5), NOW, t)).toBe('cplug.save.folders.ago_days:2');
        expect(agoText(at(3 * 3_600), NOW, t)).toBe('cplug.save.folders.ago_hours:3');
        expect(agoText(at(120), NOW, t)).toBe('cplug.save.folders.ago_minutes:2');
        expect(agoText(at(10), NOW, t)).toBe('cplug.save.folders.just_now:');
        expect(agoText(null, NOW, t)).toBe('cplug.save.folders.never:');
    });
});
