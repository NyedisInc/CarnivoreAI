/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Inspector from './Inspector.svelte';
import { setLocale } from '../../i18n/index.svelte';
import { EMPTY_SETTINGS, type TypeRow } from '../matrix/api';
import { matrix } from '../matrix/store.svelte';
import type { RouteCell, RoutesBody, Target } from './api';
import { inspector } from './store.svelte';
import { hueClass } from './logic';
import { SETTINGS, settingsInGroup } from '../../settings-page/settings-registry';

setLocale('en');

const row = (id: string, family: string): TypeRow => ({
    id, family, label_key: `notify.type.${id}.label`, description_key: `notify.type.${id}.description`,
    defaults: { outside_locked_off: id === 'alert.other', screen_surface: 'card' },
});
const TYPES = [row('session.permission', 'needs_you'), row('session.finished', 'sessions'), row('session.died', 'sessions'), row('alert.other', 'health'), row('agent.message', 'messages')];
const FAMILIES = ['needs_you', 'sessions', 'health', 'messages'].map((id) => ({ id, label_key: `notify.family.${id}` }));
const cell = (value: boolean | null, source: RouteCell['source'] = 'global', locked = false): RouteCell => ({ value, source, locked });
const COMPUTERS = [
    { install_id: 'iid_n', label: 'nostromo', self: true, online: true, syncs: true, hue: 0 },
    { install_id: 'iid_t', label: 'tower', self: false, online: true, syncs: true, hue: 1 },
    { install_id: 'iid_x', label: 'xeno', self: false, online: false, syncs: false, hue: 2 },
];
function routesBody(on: Record<string, boolean> = {}): RoutesBody {
    return {
        revision: 3, self: 'iid_n', phone_paired: true, computers: COMPUTERS,
        types: Object.fromEntries(TYPES.map((r) => {
            const locked = r.id === 'alert.other';
            const cells = Object.fromEntries(COMPUTERS.map((c) => [c.install_id, {
                app: cell(true), desk: cell(c.self ? true : null, c.self ? 'global' : 'unknown'),
                phone: locked ? cell(false, 'locked', true) : cell(r.id === 'session.finished' && c.self ? false : true),
                corner: locked ? cell(false, 'locked', true) : cell(true),
            } as Record<Target, RouteCell>]));
            return [r.id, { on: on[r.id] ?? true, locked: { phone: locked, corner: locked }, cells }];
        })),
    };
}
const STYLES = {
    revision: 1, sounds: ['ask', 'done', 'alarm', 'none'], urgencies: ['passive', 'active', 'time-sensitive'],
    styles: Object.fromEntries(TYPES.map((r) => [r.id, { sound: 'ask', urgency: 'active', source: 'default', corner: true }])),
};

interface Call { method: string; path: string; body: Record<string, unknown> | null }
function fake(opts: { on?: Record<string, boolean>; link?: string; test?: 'ok' | 'no_phone' | 'wait' } = {}) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        calls.push({ method, path, body: typeof init.body === 'string' ? JSON.parse(init.body) : null });
        if (path === '/notifications/types') return { families: FAMILIES, types: TYPES };
        if (path === '/notifications/settings' && method === 'GET') return { paused: false, link: { kind: opts.link ?? 'lan_ip', base: 'http://192.168.1.5:5001', reason: 'lan_ip_ready' } };
        if (path === '/notifications/routes') return routesBody(opts.on);
        if (path === '/notifications/master' || path === '/notifications/styles' || path.startsWith('/notifications/styles/')) return path.endsWith('master') ? routesBody(opts.on) : STYLES;
        if (path === '/notifications/test') {
            const { ApiError } = await import('../../../opscenter/api/auth.svelte');
            if (opts.test === 'no_phone') throw new ApiError('no phone', 404, 'no_phone');
            if (opts.test === 'wait') throw new ApiError('slow down', 429);
            return { ok: true, failure: null, status_code: 200, target: (JSON.parse(init.body as string) as { target: string }).target, delivered: 1 };
        }
        if (method === 'GET') return null;
        throw new Error(`unexpected ${method} ${path}`);
    }) as never;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => {
    matrix.types = []; matrix.families = []; matrix.settings = EMPTY_SETTINGS; matrix.loaded = false; matrix.problem = '';
    inspector.loaded = false; inspector.problem = ''; inspector.routes = null;
    try { localStorage.removeItem('carnivore.notify.view'); } catch {  }
});
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
});

async function render(opts: Parameters<typeof fake>[0] = {}) {
    const rig = fake(opts);
    mounted.push(mount(Inspector, { target: document.body, props: { fetcher: rig.fetcher } }));
    await vi.waitFor(() => expect(inspector.loaded && matrix.loaded).toBe(true));
    flushSync();
    return rig;
}
const q = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const qa = (sel: string) => [...document.body.querySelectorAll<HTMLElement>(sel)];
const press = async (el: HTMLElement) => { el.click(); flushSync(); await vi.waitFor(() => undefined); await Promise.resolve(); await Promise.resolve(); };
const selectGroup = (id: string) => press(q(`[data-select="${id}"]`)!);
const writes = (calls: Call[], path: string) => calls.filter((c) => c.method !== 'GET' && c.path === path).map((c) => c.body);

describe('the routing screen', () => {
    test('basic view: one switch per group, the types stay folded', async () => {
        await render();
        expect(qa('[data-group]').map((e) => e.dataset.group)).toEqual(['needs_you', 'sessions', 'health', 'messages']);
        expect(qa('[data-ins="group-switch"]').length).toBe(4);
        expect(qa('[data-type]').length).toBe(0);
        expect(q('[data-group="sessions"] .ins-gsum')!.textContent).toBe('2 of 2 on');
    });

    test('a group switch writes /master once with the whole group', async () => {
        const { calls } = await render();
        await press(q('[data-group-switch="sessions"]')!);
        expect(writes(calls, '/notifications/master')).toEqual([{ type_ids: ['session.finished', 'session.died'], value: false }]);
    });

    test('a partly-on group is mixed and its switch turns the rest on', async () => {
        const { calls } = await render({ on: { 'session.died': false } });
        const sw = q('[data-group-switch="sessions"]')!;
        expect(sw.getAttribute('aria-checked')).toBe('mixed');
        expect(sw.hasAttribute('data-mixed')).toBe(true);
        expect(q('[data-group="sessions"] .ins-gsum')!.textContent).toBe('some on: 1 of 2 on');
        await press(sw);
        expect(writes(calls, '/notifications/master')).toEqual([{ type_ids: ['session.finished', 'session.died'], value: true }]);
    });

    test('advanced view unfolds every type, each with its own switch writing one id, and is remembered', async () => {
        const { calls } = await render();
        await press(qa('[data-ins="view"] [role="radio"]').find((b) => b.textContent?.trim() === 'advanced')!);
        expect(qa('[data-type]').length).toBe(TYPES.length);
        await press(q('[data-type-switch="session.died"]')!);
        expect(writes(calls, '/notifications/master')).toEqual([{ type_ids: ['session.died'], value: false }]);
        expect(localStorage.getItem('carnivore.notify.view')).toBe('advanced');
    });

    test('a computer block row writes that computer and target for the group, and a single type writes its own id', async () => {
        const { calls } = await render();
        await selectGroup('sessions');
        const thorPhone = q('[data-computer="iid_t"][data-target="phone"]')!;
        await press(thorPhone);
        expect(writes(calls, '/notifications/routes')).toEqual([{ type_ids: ['session.finished', 'session.died'], computer: 'iid_t', target: 'phone', value: false }]);
        await press(q('[data-group="sessions"] [data-ins="caret"]')!);
        await press(q('[data-select-type="session.died"]')!);
        await press(q('[data-computer="iid_n"][data-target="app"]')!);
        expect(writes(calls, '/notifications/routes').at(-1)).toEqual({ type_ids: ['session.died'], computer: 'iid_n', target: 'app', value: false });
    });

    test('a group whose phone cell is on for one type and off for the other shows mixed', async () => {
        await render();
        await selectGroup('sessions');
        expect(q('[data-computer="iid_n"][data-target="phone"]')!.getAttribute('aria-checked')).toBe('mixed');
        expect(q('[data-computer="iid_t"][data-target="phone"]')!.getAttribute('aria-checked')).toBe('true');
    });

    test('the corner card is its own target under the desktop row', async () => {
        const { calls } = await render();
        const corner = q('[data-computer="iid_n"][data-target="corner"]')!;
        expect(corner.closest('[data-tg="desk"]')).not.toBeNull();
        await press(corner);
        expect(writes(calls, '/notifications/routes')).toEqual([{ type_ids: ['session.permission'], computer: 'iid_n', target: 'corner', value: false }]);
    });

    test('a cell a computer never wrote says not set yet and draws unticked; a locked one stays put', async () => {
        await render();
        const thorDesk = q('[data-computer="iid_t"][data-target="desk"]')!;
        expect(thorDesk.getAttribute('aria-checked')).toBe('false');
        expect(thorDesk.closest('[data-tg]')!.querySelector('[data-ins="unset"]')!.textContent).toBe('not set yet');
        await selectGroup('health');
        const lockedPhone = q('[data-computer="iid_n"][data-target="phone"]') as HTMLButtonElement;
        expect(lockedPhone.disabled).toBe(true);
        expect(lockedPhone.closest('[data-tg]')!.textContent).toContain('stays in the app');
    });

    test('a computer that does not sync gets a quiet warning, and every computer has its own tint class', async () => {
        await render();
        expect(qa('[data-ins="sync-warning"]').length).toBe(1);
        expect(q('[data-comp="iid_x"] [data-ins="sync-warning"]')).not.toBeNull();
        expect(qa('.ins-comp').map((e) => ['ins-hue-1', 'ins-hue-2', 'ins-hue-3'].find((c) => e.classList.contains(c)))).toEqual(['ins-hue-1', 'ins-hue-2', 'ins-hue-3']);
        expect([0, 1, 2, 3, 4].map(hueClass)).toEqual(['ins-hue-1', 'ins-hue-2', 'ins-hue-3', 'ins-hue-4', 'ins-hue-1']);
    });

    test('switching a type off keeps its rows and says its targets are kept', async () => {
        await render({ on: { 'session.permission': false } });
        expect(q('[data-ins="master"]')!.dataset.v).toBe('none');
        expect(q('[data-ins="sections"]')!.hasAttribute('data-disabled')).toBe(true);
        expect(qa('[data-ins="route"]').length).toBeGreaterThan(0);
        expect(q('[data-computer="iid_n"][data-target="app"]')!.getAttribute('aria-checked')).toBe('true');
        expect(q('[data-ins="cap-where"]')!.textContent).toContain('its targets are kept');
    });

    test('three tests post their own target and show their own result', async () => {
        const { calls } = await render();
        expect(qa('[data-test-button]').map((b) => b.textContent?.trim())).toEqual(['test to my phone', "test to this computer's desktop", 'test to the carnivore app']);
        for (const b of qa('[data-test-button]')) await press(b);
        await vi.waitFor(() => expect(qa('[data-ins="test-result"]').map((e) => e.textContent)).toEqual(['sent. check your phone.', 'sent. look top right.', 'sent. it pops up in the window.']));
        expect(writes(calls, '/notifications/test')).toEqual([
            { type_id: 'session.permission', target: 'phone' }, { type_id: 'session.permission', target: 'desktop' }, { type_id: 'session.permission', target: 'app' },
        ]);
        expect(qa('[data-ins="test-result"]').every((e) => e.getAttribute('role') === 'status')).toBe(true);
    });

    test('a test with no phone and a rate limit each say why', async () => {
        await render({ test: 'no_phone' });
        await press(q('[data-test-button="phone"]')!);
        await vi.waitFor(() => expect(q('[data-test="phone"] [role="status"]')!.textContent).toBe('no phone is paired with this computer.'));
    });

    test('play is an icon button named for the sound, never the word', async () => {
        await render();
        const play = q('[data-ins="play"]')!;
        expect(play.getAttribute('aria-label')).toBe('play ask');
        expect(play.textContent?.trim()).toBe('');
        expect(play.querySelector('svg')).not.toBeNull();
    });

    test('sound and urgency write PUT /styles/{type}, and passive turns the corner row off', async () => {
        const { calls } = await render();
        const sound = q('[data-ins="sound"]') as HTMLSelectElement;
        sound.value = 'alarm';
        sound.dispatchEvent(new Event('change', { bubbles: true }));
        await press(qa('[data-ins="urgency"] [role="radio"]').find((b) => b.textContent?.trim() === 'passive')!);
        expect(calls.filter((c) => c.method === 'PUT' && c.path.startsWith('/notifications/styles/')).map((c) => [c.path, c.body])).toEqual([
            ['/notifications/styles/session.permission', { sound: 'alarm' }],
            ['/notifications/styles/session.permission', { urgency: 'passive' }],
        ]);
    });

    test('the preview: one frame at a time, switched by show as, with a three line caption', async () => {
        await render();
        expect(qa('[data-frame]').map((e) => e.dataset.frame)).toEqual(['phone']);
        expect(q('[data-ins="phone-banner"]')!.textContent).toContain('cloudecode-2 wants to run');
        await press(qa('[data-ins="show-as"] [role="radio"]').find((b) => b.textContent?.trim() === 'app')!);
        expect(q('[data-frame="app"] .nc')).not.toBeNull();
        await press(qa('[data-ins="show-as"] [role="radio"]').find((b) => b.textContent?.trim() === 'desktop')!);
        expect(q('[data-ins="mac-banner"]')).not.toBeNull();
        expect(qa('[data-ins="caption"] .ins-cap__k').map((e) => e.textContent)).toEqual(['what this is', 'when it shows', 'where it appears']);
    });

    test('the link back is absent in basic and present in advanced; the warning shows only with no working link', async () => {
        await render();
        expect(q('[data-ins="link-panel"]')).toBeNull();
        expect(q('[data-ins="no-link"]')).toBeNull();
        await press(qa('[data-ins="view"] [role="radio"]').find((b) => b.textContent?.trim() === 'advanced')!);
        await vi.waitFor(() => expect(q('[data-ins="link-panel"]')).not.toBeNull());
        expect(q('[data-ins="link-kind"]')!.textContent).toBe('network address');
    });

    test('with no working link the basic view warns and its button opens the advanced view', async () => {
        await render({ link: 'none' });
        expect(q('[data-ins="link-panel"]')).toBeNull();
        expect(q('[data-ins="no-link"]')!.textContent).toContain('no working link');
        await press(q('[data-ins="no-link-go"]')!);
        await vi.waitFor(() => expect(q('[data-ins="link-panel"]')).not.toBeNull());
        expect(q('[data-ins="no-link"]')).toBeNull();
    });

    test('the phone is a phone, never an iphone, and nothing prints undefined', async () => {
        await render();
        expect(document.body.textContent!.toLowerCase()).not.toContain('iphone');
        expect(document.body.textContent).not.toMatch(/undefined|NaN|\bnull\b/);
        expect(qa('[data-ins="route"][data-target="phone"]')[0]!.textContent).toContain('phone');
    });

    test('the routing control stays the one notify-inspector setting', () => {
        expect(settingsInGroup('notifications.routing').map((s) => s.control.kind)).toEqual(['notify-inspector']);
        expect(SETTINGS.some((s) => s.control.kind === 'notify-inspector')).toBe(true);
    });
});
