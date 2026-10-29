/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { setLocale } from '../i18n/index.svelte';
import { openSettingsScreen, closeSettingsScreen } from '../settings-page/screen-host';
import { openHostsScreen, closeHostsScreen } from './screen-host';
import { closeMenuPagesExcept } from '../menu-page/menu-page-shell.svelte';

setLocale('en');
vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));

const settle = async () => {
    flushSync();
    await Promise.resolve();
    await Promise.resolve();
};
const packUp = () => !!document.querySelector('#hosts-screen .oc-page');
const settingsUp = () => !!document.querySelector('#settings-screen .oc-page, #settings-screen .settings-page');

function mount(): void {
    for (const id of ['settings-screen', 'hosts-screen']) {
        const d = document.createElement('div');
        d.id = id;
        document.body.append(d);
    }
    (window as unknown as Record<string, unknown>).CloudeWeb = { openSettingsScreen, closeSettingsScreen, openHostsScreen, closeHostsScreen };
}

test('settings opened while the pack page is up shows settings, not pack', async () => {
    mount();
    closeMenuPagesExcept('hosts');
    openHostsScreen();
    await settle();
    expect(packUp()).toBe(true);
    expect(location.hash).toMatch(/^#pack/);
    closeMenuPagesExcept('settings');
    openSettingsScreen();
    await settle();
    expect(settingsUp()).toBe(true);
    expect(packUp()).toBe(false);
});

test('an old bare #settings/pack address opens the pack page and rewrites the address without growing history', async () => {
    closeMenuPagesExcept(null);
    await settle();
    history.replaceState(null, '', '/#settings/pack');
    const before = history.length;
    closeMenuPagesExcept('settings');
    openSettingsScreen();
    await settle();
    expect(packUp()).toBe(true);
    expect(location.hash).toMatch(/^#pack/);
    expect(history.length - before).toBeLessThanOrEqual(1);
});
