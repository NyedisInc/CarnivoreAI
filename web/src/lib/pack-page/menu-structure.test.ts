/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';
import { RAIL_DESTINATIONS } from '../../opscenter/shell/rail-items';
import { SETTINGS_SECTIONS, type SectionId } from '../settings-page/settings-registry';
import SettingsNav from '../settings-page/SettingsNav.svelte';
import { MENU_PAGES } from '../menu-page/menu-pages';

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.replaceChildren();
});

test('the menu rows put pack right after providers, before settings, and have no keys row', () => {
    const ids = RAIL_DESTINATIONS.map((r) => r.id);
    expect(ids.slice(ids.indexOf('providers'), ids.indexOf('providers') + 3)).toEqual(['providers', 'hosts', 'settings']);
    expect(ids).not.toContain('keys');
    expect(RAIL_DESTINATIONS.find((r) => r.id === 'hosts')?.labelKey).toBe('opscenter.nav.hosts');
});

test('providers is a main-menu row that opens the providers (ledger) page', () => {
    const row = RAIL_DESTINATIONS.find((r) => r.id === 'providers');
    expect(row?.labelKey).toBe('opscenter.nav.providers');
    expect(typeof row?.run).toBe('function');
    expect(MENU_PAGES.find((p) => p.id === 'ledger')?.railItem).toBe('providers');
});

test('the pack menu page is registered right after dashboards, and keys is not a menu page', () => {
    const ids = MENU_PAGES.map((p) => p.id);
    expect(ids[ids.indexOf('dashboards') + 1]).toBe('hosts');
    expect(ids).not.toContain('keys');
});

test('settings sections exclude hosts and plugins, and keys follows general', () => {
    const ids = SETTINGS_SECTIONS.map((s) => s.id as string);
    expect(ids).not.toContain('hosts');
    expect(ids).not.toContain('plugins');
    expect(ids[ids.indexOf('general') + 1]).toBe('keys');
});

test('no settings rail entry carries a title attribute', () => {
    const t = (key: string): string => key;
    app = mount(SettingsNav, {
        target: document.body,
        props: { t, active: 'general', counts: null, dirty: new Set<SectionId>(), onPick: () => {}, search: (() => {}) as never },
    });
    const items = document.querySelectorAll('.st-nav button');
    expect(items.length).toBe(SETTINGS_SECTIONS.length);
    for (const item of items) expect(item.hasAttribute('title'), item.getAttribute('data-section') ?? '').toBe(false);
});
