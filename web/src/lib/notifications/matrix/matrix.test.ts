/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import MatrixPanel from './MatrixPanel.svelte';
import LinkPanel from './LinkPanel.svelte';
import { setLocale } from '../../i18n/index.svelte';
import { EMPTY_SETTINGS, type Cell, type TypeRow } from './api';
import { linkKindKey, linkReasonKey } from './logic';
import { matrix } from './store.svelte';
import { readFileSync } from 'node:fs';

setLocale('en');

const row = (id: string, family: string, over: Partial<TypeRow['defaults']> = {}): TypeRow => ({
    id, family, label_key: `notify.type.${id}.label`, description_key: `notify.type.${id}.description`,
    defaults: { outside_locked_off: false, screen_surface: 'card', ...over },
});
const TYPES: TypeRow[] = [
    row('session.permission', 'needs_you'),
    row('session.finished', 'sessions'),
    row('alert.notifications', 'health', { outside_locked_off: true }),
    row('stats.tripwire', 'in_app', { outside_locked_off: true }),
];
const FAMILIES = ['needs_you', 'sessions', 'health', 'in_app'].map((id) => ({ id, label_key: `notify.family.${id}` }));
const cell = (value: boolean, source: Cell['source'] = 'global', locked = false): Cell => ({ value, source, locked });

function settingsBody(over: { paused?: boolean; finishedPinned?: boolean; reason?: string; kind?: string } = {}) {
    return {
        revision: 1,
        paused: over.paused ?? false,
        link: { kind: over.kind ?? 'lan_ip', base: 'http://192.168.1.5:5001', reason: over.reason ?? 'mobile_sync_not_set_up' },
        defaults: { 'session.permission': true, 'session.finished': true },
        screen: {
            'session.permission': cell(true), 'session.finished': cell(true), 'alert.notifications': cell(true), 'stats.tripwire': cell(true),
        },
        ticks: {
            d_aaaaaaaaaaaa: {
                'session.permission': cell(true), 'session.finished': cell(true, over.finishedPinned ? 'local' : 'global'),
                'alert.notifications': cell(false, 'locked', true), 'stats.tripwire': cell(false, 'locked', true),
            },
            'webpush:abcd1234': { 'session.permission': cell(true), 'session.finished': cell(false, 'default') },
        },
        destinations: [{ id: 'd_aaaaaaaaaaaa', kind: 'slack', name: 'ops channel', enabled: true, scope: 'global' }],
        sync: null,
    };
}

interface Call { method: string; path: string; body: Record<string, unknown> | null }

function fake(body: ReturnType<typeof settingsBody>, answers: Record<string, () => unknown> = {}) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        calls.push({ method, path, body: typeof init.body === 'string' ? JSON.parse(init.body) : null });
        const key = `${method} ${path}`;
        if (answers[key]) return answers[key]!();
        if (path === '/notifications/types') return { families: FAMILIES, types: TYPES, kinds: [] };
        if (path === '/notifications/settings' && method === 'GET') return body;
        if (path === '/notifications/settings' && method === 'PUT') return body;
        if (path === '/notifications/ticks') return { revision: 2, cell: cell(false) };
        if (path === '/notifications/defaults') return { revision: 2, defaults: { 'session.permission': true, 'session.finished': false } };
        if (path.startsWith('/notifications/overrides')) return { revision: 2, reset: true };
        throw new Error(`unexpected ${key}`);
    }) as never;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => {
    matrix.types = []; matrix.families = []; matrix.settings = EMPTY_SETTINGS; matrix.loaded = false; matrix.problem = ''; matrix.localOnly = false;
});
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
    delete (window as { matchMedia?: unknown }).matchMedia;
});

async function render(component: typeof MatrixPanel | typeof LinkPanel, body: ReturnType<typeof settingsBody>, answers: Record<string, () => unknown> = {}) {
    const rig = fake(body, answers);
    mounted.push(mount(component, { target: document.body, props: { fetcher: rig.fetcher } }));
    await vi.waitFor(() => expect(matrix.loaded).toBe(true));
    flushSync();
    return rig;
}
const q = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const check = (id: string) => q(`[data-mx-cell="${id}"] [data-mx="check"]`) as HTMLButtonElement;
const press = async (el: HTMLElement) => { el.click(); flushSync(); await Promise.resolve(); await Promise.resolve(); };

describe('the desktop matrix', () => {
    test('rows are grouped by family and columns are screen, defaults, each destination and a web push device', async () => {
        await render(MatrixPanel, settingsBody());
        expect([...document.body.querySelectorAll('[data-mx="family"]')].map((e) => e.textContent)).toEqual(['needs you', 'sessions', 'health', 'in-app only']);
        expect([...document.body.querySelectorAll('[data-mx-col]')].map((e) => e.getAttribute('data-mx-col'))).toEqual(['screen', 'defaults', 'd_aaaaaaaaaaaa', 'webpush:abcd1234']);
        expect(document.body.querySelectorAll('[data-mx-row]').length).toBe(TYPES.length);
        expect(q('[data-mx-col="webpush:abcd1234"]')!.textContent).toContain('web push device 1234');
    });

    test('a locked cell is disabled and says why; an open cell is not disabled', async () => {
        await render(MatrixPanel, settingsBody());
        expect(check('screen:session.permission').disabled).toBe(false);
        expect(q('[data-mx-cell="screen:session.permission"] [data-mx="why"]')).toBeNull();
        for (const id of ['d_aaaaaaaaaaaa:alert.notifications', 'd_aaaaaaaaaaaa:stats.tripwire']) expect(check(id).disabled).toBe(true);
        expect(q('[data-mx-cell="d_aaaaaaaaaaaa:stats.tripwire"] [data-mx="why"]')!.textContent).toBe('stays here');
        expect(check('screen:session.finished').disabled).toBe(false);
        expect(check('d_aaaaaaaaaaaa:session.finished').disabled).toBe(false);
    });

    test('a cell shows its source; a pinned cell shows the local badge and reset to global calls DELETE /overrides', async () => {
        const rig = await render(MatrixPanel, settingsBody({ finishedPinned: true }));
        expect(q('[data-mx-cell="screen:session.finished"] [data-mx="source"]')!.textContent).toBe('global');
        expect(q('[data-mx-cell="d_aaaaaaaaaaaa:session.finished"] [data-mx="local-badge"]')!.textContent).toBe('local');
        expect(q('[data-mx-cell="d_aaaaaaaaaaaa:session.permission"] [data-mx="local-badge"]')).toBeNull();
        await press(q('[data-mx-cell="d_aaaaaaaaaaaa:session.finished"] [data-mx="reset"]')!);
        const del = rig.calls.find((c) => c.method === 'DELETE')!;
        expect(decodeURIComponent(del.path)).toBe('/notifications/overrides?path=tick/d_aaaaaaaaaaaa/session.finished');
    });

    test('a tick writes PUT /ticks without a scope, so the server picks global or the existing pin', async () => {
        const rig = await render(MatrixPanel, settingsBody());
        await press(check('screen:session.finished'));
        const put = rig.calls.find((c) => c.method === 'PUT' && c.path === '/notifications/ticks')!;
        expect(put.body).toEqual({ column: 'screen', type_id: 'session.finished', value: false });
        expect(check('screen:session.finished').getAttribute('aria-checked')).toBe('false');
    });

    test('with "this computer only" on, a tick is written as a local pin', async () => {
        const rig = await render(MatrixPanel, settingsBody());
        await press(q('[data-mx="local-only"]')!);
        await press(check('d_aaaaaaaaaaaa:session.finished'));
        expect(rig.calls.find((c) => c.path === '/notifications/ticks')!.body).toEqual({ column: 'd_aaaaaaaaaaaa', type_id: 'session.finished', value: false, scope: 'local' });
    });

    test('the defaults column is what a new destination starts with and writes PUT /defaults; a no-out row is locked there too', async () => {
        const rig = await render(MatrixPanel, settingsBody());
        expect(q('[data-mx-col="defaults"]')!.textContent).toContain('what a new destination starts with');
        expect(check('defaults:session.finished').getAttribute('aria-checked')).toBe('true');
        expect(check('defaults:stats.tripwire').disabled).toBe(true);
        await press(check('defaults:session.finished'));
        expect(rig.calls.find((c) => c.path === '/notifications/defaults')!.body).toEqual({ type_id: 'session.finished', value: false });
        expect(check('defaults:session.finished').getAttribute('aria-checked')).toBe('false');
    });

    test('a failed write is shown as the problem line', async () => {
        await render(MatrixPanel, settingsBody(), { 'PUT /notifications/ticks': () => { throw new Error('keychain says no'); } });
        await press(check('screen:session.finished'));
        await vi.waitFor(() => expect(q('[data-mx="problem"]')).not.toBeNull());
    });
});

describe('below 1024px', () => {
    test('one column at a time with a picker on top; switching the picker changes the cells', async () => {
        (window as unknown as { matchMedia: unknown }).matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });
        const rig = await render(MatrixPanel, settingsBody());
        expect(q('[data-mx="desktop"]')).toBeNull();
        const picker = q('[data-mx="picker"]') as HTMLSelectElement;
        expect([...picker.options].map((o) => o.value)).toEqual(['screen', 'defaults', 'd_aaaaaaaaaaaa', 'webpush:abcd1234']);
        expect(q('[data-mx-cell="screen:session.finished"]')).not.toBeNull();
        expect(q('[data-mx-cell="d_aaaaaaaaaaaa:session.finished"]')).toBeNull();
        picker.value = 'd_aaaaaaaaaaaa';
        picker.dispatchEvent(new Event('change', { bubbles: true }));
        flushSync();
        expect(q('[data-mx-cell="screen:session.finished"]')).toBeNull();
        expect(check('d_aaaaaaaaaaaa:stats.tripwire').disabled).toBe(true);
        await press(check('d_aaaaaaaaaaaa:session.finished'));
        expect(rig.calls.find((c) => c.path === '/notifications/ticks')!.body).toMatchObject({ column: 'd_aaaaaaaaaaaa', type_id: 'session.finished' });
    });
});

describe('the link and the pause switch', () => {
    test('the kind and the reason read in plain words', async () => {
        await render(LinkPanel, settingsBody());
        expect(q('[data-mx="link-kind"]')!.textContent).toBe('network address');
        expect(q('[data-mx="link-base"]')!.textContent).toBe('http://192.168.1.5:5001');
        expect(q('[data-mx="link-reason"]')!.textContent).toBe('mobile sync is not set up, so outside notifications link to this computer on your network instead.');
    });

    test('every reason code the server can send has its own sentence, and an unknown code falls back', () => {
        for (const code of ['mobile_sync_ready', 'mobile_sync_not_set_up', 'local_name_ready', 'lan_ip_ready', 'bound_loopback_only', 'bound_host_unknown', 'no_lan_address']) {
            expect(linkReasonKey(code)).toBe(`settings.notify.link.reason.${code}`);
        }
        expect(linkReasonKey('something_new')).toBe('settings.notify.link.reason.unknown');
        expect(linkKindKey('mobile_sync')).toBe('settings.notify.link.kind.mobile_sync');
        expect(linkKindKey('x')).toBe('settings.notify.link.kind.none');
    });

    test('a no-link answer says why', async () => {
        await render(LinkPanel, { ...settingsBody({ kind: 'none', reason: 'bound_loopback_only' }), link: { kind: 'none', base: '', reason: 'bound_loopback_only' } });
        expect(q('[data-mx="link-base"]')).toBeNull();
        expect(q('[data-mx="link-reason"]')!.textContent).toContain('only listens on this computer');
    });

    test('the pause switch reflects the state and writes PUT /settings {paused}', async () => {
        const rig = await render(LinkPanel, settingsBody({ paused: false }));
        const sw = q('[data-mx="pause"]')!;
        expect(sw.getAttribute('aria-checked')).toBe('false');
        expect(sw.textContent).toContain('pause all outside delivery');
        await press(sw);
        expect(rig.calls.find((c) => c.method === 'PUT' && c.path === '/notifications/settings')!.body).toEqual({ paused: true });
        expect(q('[data-mx="pause"]')!.getAttribute('aria-checked')).toBe('true');
    });
});

describe('row description face', () => {
    test('the description is set in the mono face at body size on its own, outside the table that used to set it', () => {
        const css = readFileSync('src/lib/notifications/matrix/matrix.css', 'utf8');
        const rule = /\.mx-desc\s*{([^}]*)}/.exec(css)?.[1] ?? '';
        expect(rule).toContain('font-family: var(--oc-font)');
        expect(rule).toContain('font-size: var(--oc-fs-body)');
    });
});

describe('sticky first column', () => {
    test('the pinned notification column paints the page content token, not the lighter panel token', () => {
        const css = readFileSync('src/lib/notifications/matrix/matrix.css', 'utf8');
        const rule = /\.mx-table \.mx-type\s*{([^}]*)}/.exec(css)?.[1] ?? '';
        expect(rule).toContain('position: sticky');
        expect(rule).toMatch(/background:\s*var\(--oc-ground-content\)/);
        expect(rule).not.toMatch(/background:\s*var\(--oc-ground-panel\)/);
        const page = readFileSync('src/opscenter/page.css', 'utf8');
        const body = /\.oc-page\s*{([^}]*)}/.exec(page)?.[1] ?? '';
        expect(body).toMatch(/background:\s*var\(--oc-ground-content\)/);
    });
});
