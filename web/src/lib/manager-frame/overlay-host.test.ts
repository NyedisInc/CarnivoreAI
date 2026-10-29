/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';

import { createOverlayHost } from './overlay-host';
import Fixture from './overlay-host-fixture.svelte';
import { initMenuPageShell, menuPageState, resetMenuPageShell } from '../menu-page/menu-page-shell.svelte';
import '../dynamic-tabs/builtin';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import * as Bar from '../drawer/bar';

const CONTAINER_ID = 'settings-screen';

let stopShell: () => void = () => {};

beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div>';
    const container = document.createElement('div');
    container.id = CONTAINER_ID;
    document.body.append(container);

    resetMenuPageShell();
    sidebarTabs.select('agents');
    stopShell = initMenuPageShell(document);

    Bar.reset();
    delete (window as unknown as Record<string, unknown>).CloudeWeb;
});

afterEach(() => {
    stopShell();
    Bar.reset();
    delete (window as unknown as Record<string, unknown>).CloudeWeb;
    document.body.innerHTML = '';
});

test('open() paints the page and settles the shell on the SAME turn, no await', () => {
    const host = createOverlayHost(CONTAINER_ID, Fixture, '#settings');

    const opened = host.open();

    expect(opened).toBe(true);
    expect(document.getElementById(CONTAINER_ID)!.querySelector('.fixture-page')).not.toBeNull();
    expect(sidebarTabs.stored).toBe('menu');
    expect(menuPageState.open).toBe('settings');
    expect(document.body.classList.contains('menu-page-open')).toBe(true);
});

test('settings run through the bar\'s run() (what a menu row\'s action calls) opens the SAME way a real click would', () => {
    const host = createOverlayHost(CONTAINER_ID, Fixture, '#settings');
    (window as unknown as { CloudeWeb: Record<string, unknown> }).CloudeWeb = {
        openSettingsScreen: () => host.open(),
    };

    // no longer holds
    Bar.run('settings', null);

    expect(document.getElementById(CONTAINER_ID)!.querySelector('.fixture-page'),
        'settings actually painted, not just "will, eventually"').not.toBeNull();
    expect(sidebarTabs.stored).toBe('menu');
    expect(menuPageState.open).toBe('settings');
});

test('a second open reuses the mounted page and still settles synchronously', () => {
    const host = createOverlayHost(CONTAINER_ID, Fixture, '#settings');
    host.open();
    host.close();
    sidebarTabs.select('agents');

    host.open();

    expect(document.getElementById(CONTAINER_ID)!.querySelector('.fixture-page')).not.toBeNull();
    expect(sidebarTabs.stored).toBe('menu');
    expect(menuPageState.open).toBe('settings');

    host.unmount();
});
