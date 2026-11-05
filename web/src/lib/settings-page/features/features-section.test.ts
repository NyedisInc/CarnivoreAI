/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../resource-push/boot', () => ({
    resourcePush: () => ({ isLive: () => true, onChange: () => () => {}, pushOrPoll: () => () => {} }),
}));

const toggleSwarm = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock('../../swarm-switch/control.svelte', async (actual) => ({ ...(await actual<object>()), toggleSwarm, startSwarmSwitch: () => {} }));
import { swarmSwitch } from '../../swarm-switch/control.svelte';
import SettingsScreen from '../SettingsScreen.svelte';
import { settingsDoc } from '../settings-doc.svelte';
import { setLocale, t as realT } from '../../i18n/index.svelte';
import type { Translate } from '../../sessions/types';
import type { CplugRow } from '../../plugins-page/cplugs-adapter';

setLocale('en');

const WORDS: Record<string, string> = {
    'cplug.publicboard.name': 'public review links',
    'cplug.reviewboard.name': 'review board',
    'cplug.timemachine.name': 'time machine check',
    'cplug.acme.name': 'acme clock',
    'cplug.huddle.name': 'task manager',
    'cplug.x.settings.mode': 'review mode',
};
const t: Translate = (key, params) => WORDS[key] ?? realT(key, params);

const row = (id: string, extra: Partial<CplugRow> = {}): CplugRow => ({
    id, name_key: `cplug.${id}.name`, version: '1.0.0', tier: 'builtin', enabled: true, state: 'active', revision: 1, permissions: { app: [] }, ...extra,
});
const PUBLICBOARD = row('publicboard', { enabled: false, state: 'disabled' });
const REVIEWBOARD = row('reviewboard');
const DEV = row('tmdevtools', { tier: 'dev' });
const STORE = row('acme', { tier: 'catalog', runtime: 'sidecar', name: 'acme clock', publisher: 'acme' });
const REVIEWBOARD_BARE = row('flow');
const HUDDLE = row('huddle', { settings: { wrap: true }, settings_schema: { version: 1, fields: { wrap: { kind: 'boolean', labelKey: 'cplug.huddle.settings.wrap', default: true } } } });

let listing: CplugRow[] = [];
let developerMode = false;
let puts: Array<{ url: string; body: Record<string, unknown> }> = [];
let handle: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 40; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

function answer(url: string, init?: RequestInit): Response {
    const one = /\/cplugs\/([a-z0-9_.-]+)$/.exec(url);
    if (init?.method === 'PUT' && one) {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        puts.push({ url, body });
        listing = listing.map((r) => (r.id === one[1] ? { ...r, enabled: body.enabled === true, state: body.enabled === true ? 'active' : 'disabled' } : r));
    }
    if (one) return new Response(JSON.stringify(listing.find((r) => r.id === one[1])), { status: 200 });
    if (url.endsWith('/cplugs')) return new Response(JSON.stringify({ cplugs: listing }), { status: 200 });
    return new Response(JSON.stringify({ workspace: {}, server_prefs: { developer_mode: developerMode }, server: {}, notifications: {} }), { status: 200 });
}

async function mountPage(embedded = true): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: { embedded, t } }) as Record<string, unknown>;
    flushSync();
    (handle as unknown as { show(): void }).show();
    await settle();
    return target;
}

async function openFeatures(root: HTMLElement): Promise<HTMLElement> {
    root.querySelector<HTMLButtonElement>('.st-nav button[data-section="features"]')!.click();
    await settle();
    return root.querySelector<HTMLElement>('[data-screen="features"]')!;
}

const cardNames = (screen: HTMLElement): string[] =>
    [...screen.querySelectorAll('.catalog-card__title, .mgr-card__name')].map((el) => el.textContent?.trim() ?? '');

beforeEach(() => {
    listing = [PUBLICBOARD, REVIEWBOARD, STORE];
    developerMode = false;
    puts = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => answer(String(input), init)));
    settingsDoc.discard();
    window.location.hash = '';
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    settingsDoc.discard();
    document.body.innerHTML = '';
    window.location.hash = '';
    vi.unstubAllGlobals();
});

describe('settings > features', () => {
    test('the rail opens the features heading with the overview of every built-in', async () => {
        const root = await mountPage();
        expect(root.querySelector('[data-st-features-heading]')?.textContent).toBe('features');
        expect(root.querySelector('.st-nav button[data-section="features"] .st-nav__label')?.textContent).toBe('all features');
    });

    test('an off compiled-in item (public review links) is listed with a switch that turns it on', async () => {
        const screen = await openFeatures(await mountPage());
        expect(cardNames(screen)).toEqual(['public review links', 'review board']);
        const off = [...screen.querySelectorAll<HTMLElement>('[role="switch"]')];
        expect(off.map((el) => el.getAttribute('aria-checked'))).toEqual(['false', 'true']);
        off[0]!.click();
        await settle();
        expect(puts).toHaveLength(1);
        expect(puts[0]!.url).toMatch(/\/cplugs\/publicboard$/);
        expect(puts[0]!.body.enabled).toBe(true);
        expect(screen.querySelectorAll<HTMLElement>('[role="switch"]')[0]!.getAttribute('aria-checked')).toBe('true');
    });

    test('a store plugin (sidecar) is not listed under features', async () => {
        const screen = await openFeatures(await mountPage());
        expect(cardNames(screen)).not.toContain('acme clock');
    });

    test('the dev tier is listed only while developer mode is on', async () => {
        listing = [PUBLICBOARD, DEV];
        const off = await openFeatures(await mountPage());
        expect(cardNames(off)).toEqual(['public review links']);
        unmount(handle!);
        handle = null;
        document.body.innerHTML = '';
        settingsDoc.discard();
        developerMode = true;
        const on = await openFeatures(await mountPage());
        expect(cardNames(on)).toEqual(['public review links', 'task-manager-dev-tools']);
    });

    const withSettings = (id: string, extra: Partial<CplugRow> = {}): CplugRow =>
        row(id, { settings: { mode: 1 }, settings_schema: { version: 1, fields: { mode: { kind: 'number', labelKey: 'cplug.x.settings.mode', default: 1 } } }, ...extra });
    const featureIdsIn = (root: HTMLElement): string[] =>
        [...root.querySelectorAll<HTMLElement>('[data-st-features-list] button[data-plugin]')].map((el) => el.dataset.plugin!);
    const pluginIdsIn = (root: HTMLElement): string[] =>
        [...root.querySelectorAll<HTMLElement>('[data-st-plugins-list] button[data-plugin]')].map((el) => el.dataset.plugin!);

    test('two headed sections close the rail, features then plugins, features opening with its overview', async () => {
        listing = [withSettings('reviewboard'), withSettings('notes', { tier: 'catalog', runtime: 'sidecar', name: 'notes' })];
        const root = await mountPage();
        const headings = [...root.querySelectorAll<HTMLElement>('.st-nav h3')].map((el) => el.textContent);
        expect(headings).toEqual(['features', 'plugins']);
        const first = root.querySelector<HTMLElement>('[data-st-features-list] button');
        expect(first?.dataset.section).toBe('features');
    });

    test('an enabled feature with settings has a features entry, a disabled one none, and a store plugin appears only under plugins', async () => {
        listing = [withSettings('reviewboard'), withSettings('publicboard', { enabled: false, state: 'disabled' }), withSettings('notes', { tier: 'catalog', runtime: 'sidecar', name: 'notes' }), row('flow')];
        const root = await mountPage();
        expect(featureIdsIn(root)).toEqual(['reviewboard']);
        expect(pluginIdsIn(root)).toEqual(['notes']);
    });

    test('the features heading always shows; the plugins heading only when a store plugin has settings', async () => {
        listing = [PUBLICBOARD, STORE];
        const root = await mountPage();
        expect(root.querySelector('[data-st-features-heading]')).not.toBeNull();
        expect(root.querySelector('[data-st-plugins-heading]')).toBeNull();
    });

    test('settings search finds a feature\'s setting under its features entry', async () => {
        listing = [withSettings('reviewboard')];
        const root = await mountPage();
        const input = root.querySelector<HTMLInputElement>('input[type="search"], input')!;
        input.value = 'review mode';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(root.querySelector('[data-st-features-list] button[data-plugin="reviewboard"] .st-nav__count')?.textContent).toBe('1');
    });

    test('an old plugin link to an enabled built-in with settings opens its features entry', async () => {
        listing = [withSettings('huddle')];
        window.location.hash = '#settings/plugin/huddle';
        const root = await mountPage(false);
        expect(root.querySelector('[data-plugin-entry="huddle"]')).not.toBeNull();
        expect(root.querySelector('[data-st-features-list] button[data-plugin="huddle"][aria-current="page"]')).not.toBeNull();
        expect(window.location.hash).toBe('#settings/plugin/huddle');
    });

    test('its address round-trips and opens the item with its switch in the pane', async () => {
        window.location.hash = '#settings/features/publicboard';
        const root = await mountPage(false);
        const screen = root.querySelector<HTMLElement>('[data-screen="features"]')!;
        expect(screen).not.toBeNull();
        expect(screen.querySelector('[data-plugin-pane-switch="publicboard"]')).not.toBeNull();
    });

    test('the bare section address closes the open pane', async () => {
        window.location.hash = '#settings/features/publicboard';
        const root = await mountPage(false);
        expect(root.querySelector('[data-plugin-pane-switch="publicboard"]')).not.toBeNull();
        window.location.hash = '#settings/features';
        (handle as unknown as { show(): void }).show();
        await settle();
        expect(root.querySelector('[data-plugin-pane-switch]')).toBeNull();
        expect(root.querySelectorAll('[data-screen="features"] [role="switch"]').length).toBeGreaterThan(0);
    });

    test('the old plugin link to a disabled built-in hands over to its features row without trapping back: one press returns to where the owner was', async () => {
        listing = [{ ...HUDDLE, enabled: false, state: 'disabled' }];
        window.history.replaceState(null, '', '#settings/general');
        window.history.pushState(null, '', '#settings/plugin/huddle');
        const root = await mountPage(false);
        expect(window.location.hash).toBe('#settings/features/huddle');
        expect(root.querySelector('[data-screen="features"]')).not.toBeNull();
        window.history.back();
        await new Promise((resolve) => setTimeout(resolve, 100));
        expect(window.location.hash).toBe('#settings/general');
    });
});

describe('settings > features, the Swarm switch (#2701, Joe (ccsliinc), 2026-10-30)', () => {
    afterEach(() => {
        swarmSwitch.data = null;
        toggleSwarm.mockClear();
    });

    test('a swarm row is listed with a switch that reflects the store and calls the swarm route', async () => {
        swarmSwitch.data = { enabled: false };
        const screen = await openFeatures(await mountPage());
        expect(cardNames(screen)).toContain('swarm');
        const card = [...screen.querySelectorAll<HTMLElement>('[role="switch"]')].find((el) => /swarm/.test(el.getAttribute('aria-label') ?? el.closest('[data-id], li, article')?.textContent ?? ''))!;
        expect(card, 'the swarm switch is drawn').toBeTruthy();
        expect(card.getAttribute('aria-checked'), 'off in the store reads off').toBe('false');
        card.click();
        await settle();
        expect(toggleSwarm).toHaveBeenCalledWith(true);
        expect(puts, 'it never goes through the cplugs routes').toHaveLength(0);
        swarmSwitch.data = { enabled: true };
        await settle();
        expect(card.getAttribute('aria-checked'), 'the store flip repaints it').toBe('true');
    });

    test('clicking the swarm card opens the task manager pane, where its settings live, while that row exists', async () => {
        swarmSwitch.data = { enabled: true };
        listing = [HUDDLE];
        const screen = await openFeatures(await mountPage());
        screen.querySelector<HTMLElement>('[data-item-id="switch:swarm"]')!.click();
        await settle();
        expect(screen.querySelector('[data-plugin-pane-switch="huddle"]')).not.toBeNull();
    });

    test('NEGATIVE: with no task manager row, clicking the swarm card opens nothing', async () => {
        swarmSwitch.data = { enabled: true };
        listing = [REVIEWBOARD];
        const screen = await openFeatures(await mountPage());
        screen.querySelector<HTMLElement>('[data-item-id="switch:swarm"]')!.click();
        await settle();
        expect(screen.querySelector('[data-plugin-pane-switch]')).toBeNull();
    });

    test('NEGATIVE: no answer from the swarm route yet, no row', async () => {
        const screen = await openFeatures(await mountPage());
        expect(cardNames(screen)).not.toContain('swarm');
    });
});
