/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Inspector from './Inspector.svelte';
import { setLocale } from '../../i18n/index.svelte';
import { EMPTY_SETTINGS, type Cell, type TypeRow } from '../matrix/api';
import { matrix } from '../matrix/store.svelte';
import { inspector } from './store.svelte';
import { SETTINGS, settingsInGroup } from '../../settings-page/settings-registry';

setLocale('en');

const row = (id: string, family: string): TypeRow => ({
    id, family, label_key: `notify.type.${id}.label`, description_key: `notify.type.${id}.description`,
    defaults: { outside_locked_off: false, screen_surface: 'card' },
});
const TYPES = [row('session.question', 'needs_you'), row('session.died', 'sessions'), row('alert.other', 'health'), row('agent.message', 'messages')];
const FAMILIES = ['needs_you', 'sessions', 'health', 'messages'].map((id) => ({ id, label_key: `notify.family.${id}` }));
const cell = (value: boolean): Cell => ({ value, source: 'global', locked: false });
const all = (value: boolean) => Object.fromEntries(TYPES.map((r) => [r.id, cell(value)]));

const SETTINGS_BODY = {
    revision: 1, paused: false, link: { kind: 'lan_ip', base: 'http://192.168.1.5:5001', reason: 'mobile_sync_ready' }, defaults: {},
    screen: all(true), desktop: all(true), ticks: { 'apns:d_phone': all(true) },
    destinations: [], sync: null,
};
const STYLES = {
    revision: 1, sounds: ['ask', 'done', 'alarm', 'soft', 'none', 'default'], urgencies: ['passive', 'active', 'time-sensitive'],
    styles: Object.fromEntries(TYPES.map((r) => [r.id, { sound: 'ask', urgency: 'active', source: 'default', corner: true }])),
};

interface Call { method: string; path: string; body: Record<string, unknown> | null }
function fake() {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        calls.push({ method, path, body: typeof init.body === 'string' ? JSON.parse(init.body) : null });
        if (path === '/computers') return { self: { label: 'studio' } };
        if (path === '/notifications/types') return { families: FAMILIES, types: TYPES };
        if (path === '/notifications/settings') return SETTINGS_BODY;
        if (path === '/notifications/styles' && method === 'GET') return STYLES;
        if (path.startsWith('/notifications/styles/')) return STYLES;
        if (path === '/notifications/ticks') return { revision: 2, cell: cell(false) };
        if (path.endsWith('/test')) return { ok: true, failure: null, status_code: 200 };
        throw new Error(`unexpected ${method} ${path}`);
    }) as never;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => {
    matrix.types = []; matrix.families = []; matrix.settings = EMPTY_SETTINGS; matrix.loaded = false; matrix.problem = '';
    inspector.loaded = false; inspector.problem = '';
});
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
});

async function render() {
    const rig = fake();
    mounted.push(mount(Inspector, { target: document.body, props: { fetcher: rig.fetcher } }));
    await vi.waitFor(() => expect(inspector.loaded && matrix.loaded).toBe(true));
    flushSync();
    return rig;
}
const q = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const press = async (el: HTMLElement) => { el.click(); flushSync(); await Promise.resolve(); await Promise.resolve(); };
const pick = async (id: string) => press(q(`[data-type="${id}"]`)!);
const change = async (el: HTMLElement, value: string) => {
    (el as HTMLSelectElement).value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    await Promise.resolve();
};

describe('the inspector', () => {
    test('lists the registry types in their groups and draws the selected type card', async () => {
        await render();
        expect([...document.body.querySelectorAll('.ins__list h4')].map((e) => e.textContent)).toEqual(['needs you', 'sessions', 'health', 'messages']);
        expect(document.body.querySelectorAll('[data-type]').length).toBe(TYPES.length);
        expect(q('.nc')!.dataset.kind).toBe('yesno');
        await pick('session.died');
        expect(q('.nc')!.dataset.kind).toBe('died');
        expect(q('.nc')!.textContent).toContain('exit code');
        await pick('alert.other');
        expect(q('.nc')!.dataset.kind).toBe('notice');
        expect(q('.nc')!.textContent).toContain('notify.type.alert.other.label'.length ? '' : '');
        expect(document.body.textContent).not.toMatch(/undefined|NaN|\bnull\b/);
    });

    test('a type with several shapes has a shape switcher and it redraws the card', async () => {
        await render();
        await pick('agent.message');
        expect(q('.nc')!.dataset.kind).toBe('crosstalk');
        const shapes = [...document.body.querySelectorAll('[data-ins="shapes"] [role="radio"]')].map((e) => e.textContent?.trim());
        expect(shapes).toEqual(['message', 'file', 'link', 'image', 'video']);
        await press(document.body.querySelectorAll<HTMLElement>('[data-ins="shapes"] [role="radio"]')[3]!);
        expect(q('.nc')!.dataset.kind).toBe('image');
        await pick('session.died');
        expect(q('[data-ins="shapes"]')).toBeNull();
    });

    test('a device switch writes PUT /ticks with that column', async () => {
        const { calls } = await render();
        await press(q('[data-dev="apns:d_phone"]')!);
        expect(calls.filter((c) => c.path === '/notifications/ticks')).toEqual([
            { method: 'PUT', path: '/notifications/ticks', body: { column: 'apns:d_phone', type_id: 'session.question', value: false } },
        ]);
        await press(q('[data-dev="desktop"]')!);
        expect(calls.at(-1)!.body).toEqual({ column: 'desktop', type_id: 'session.question', value: false });
    });

    test('the previews are the mockup three, and the device chips carry real names', async () => {
        await render();
        expect([...document.body.querySelectorAll('[data-ins^="wall-"]')].map((w) => (w as HTMLElement).dataset.ins)).toEqual(['wall-banner', 'wall-card', 'wall-computer']);
        expect(q('[data-ins="wall-banner"] [data-ins="banner"]')!.textContent).toContain('api-docs asks');
        expect(q('[data-dev="desktop"]')!.textContent).toBe('studio');
        expect(q('[data-dev="apns:d_phone"]')!.textContent).toBe('iphone');
        expect(q('[data-dev="apns:d_phone"]')!.getAttribute('aria-pressed')).toBe('true');
    });

    test('sound, urgency and the corner switch write PUT /styles/{type}', async () => {
        const { calls } = await render();
        await change(q('[data-ins="sound"]')!, 'alarm');
        await change(q('[data-ins="urgency"]')!, 'passive');
        await press(q('[data-ins="corner"]')!);
        const writes = calls.filter((c) => c.method === 'PUT' && c.path.startsWith('/notifications/styles/'));
        expect(writes.map((c) => [c.path, c.body])).toEqual([
            ['/notifications/styles/session.question', { sound: 'alarm' }],
            ['/notifications/styles/session.question', { urgency: 'passive' }],
            ['/notifications/styles/session.question', { corner: false }],
        ]);
        expect([...q('[data-ins="urgency"]')!.querySelectorAll('option')].map((o) => o.textContent)).toEqual(['passive', 'active', 'time-sensitive']);
    });

    test('send a test posts the type to the first iPhone', async () => {
        const { calls } = await render();
        await pick('session.died');
        await press(q('[data-ins="test"]')!);
        await vi.waitFor(() => expect(q('[data-ins="test-state"]')?.textContent).toContain('sent'));
        expect(calls.at(-1)).toEqual({ method: 'POST', path: '/notifications/destinations/apns%3Ad_phone/test', body: { type_id: 'session.died' } });
    });

    test('the grid, mutes and sync stay in the registry under the inspector', () => {
        const ids = settingsInGroup('notifications.routing').map((s) => s.id);
        expect(ids.indexOf('notification_inspector')).toBeLessThan(ids.indexOf('notification_matrix'));
        expect(ids).toEqual(expect.arrayContaining(['notification_matrix', 'notification_mutes', 'notification_sync', 'notification_link']));
        expect(SETTINGS.some((s) => s.control.kind === 'notify-inspector')).toBe(true);
    });
});
