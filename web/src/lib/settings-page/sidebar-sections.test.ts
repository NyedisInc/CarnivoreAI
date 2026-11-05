/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import SettingsScreen from './SettingsScreen.svelte';
import { settingsDoc } from './settings-doc.svelte';
import { sectionShown } from '../drawer/section-visibility.svelte';
import { swarmSwitch } from '../swarm-switch/control.svelte';
import { viewMenuNodes } from '../session-list/view-choices';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
let handle: Record<string, unknown> | null = null;

/** Let pending promises and effects run. */
async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ workspace: {}, server_prefs: {}, server: {}, notifications: {} }), { status: 200 })));
    settingsDoc.discard();
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    settingsDoc.discard();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

async function openSidebarTab(): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: { embedded: true } }) as Record<string, unknown>;
    flushSync();
    await settle();
    target.querySelector<HTMLButtonElement>('.st-nav button[data-section="appearance"]')!.click();
    await settle();
    target.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="sidebar"]')!.click();
    await settle();
    return target;
}

const switchOf = (root: HTMLElement, id: string) => root.querySelector<HTMLElement>(`[data-setting-id="${id}"] [role="switch"]`);

test('Settings > appearance > sidebar has a switch for each section, on by default, writing the same stored value', async () => {
    const root = await openSidebarTab();
    for (const [id, section] of [['sidebar_show_open', 'open'], ['sidebar_show_sleeping', 'sleeping']] as const) {
        const one = switchOf(root, id);
        expect(one, id).not.toBeNull();
        expect(one!.getAttribute('aria-checked'), id).toBe('true');
        one!.click();
        await settle();
        expect(sectionShown(section), id).toBe(false);
        expect(switchOf(root, id)!.getAttribute('aria-checked'), id).toBe('false');
    }
});

test('the view menu no longer lists show open or show sleeping', () => {
    const ids = viewMenuNodes().map((node) => node.id);
    expect(ids).not.toContain('show-open');
    expect(ids).not.toContain('show-sleeping');
    expect(ids).toContain('hide-empty-sections');
});

test('the view menu lists show leaders only while the Swarm switch is on (#2784)', () => {
    try {
        swarmSwitch.data = { enabled: false };
        expect(viewMenuNodes().map((node) => node.id)).not.toContain('show-leaders');
        swarmSwitch.data = { enabled: true };
        expect(viewMenuNodes().map((node) => node.id)).toContain('show-leaders');
    } finally {
        swarmSwitch.data = null;
    }
});
