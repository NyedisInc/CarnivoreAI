/** @vitest-environment jsdom */
import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { unmountPanel } from '../mount';
import type { CatalogHost } from '../catalog/catalog';
import type { CatalogItem, InstalledItem } from '../catalog/types';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const anyNode = (): unknown =>
    new Proxy(function () {}, {
        get: (target, prop) => (prop in target ? (target as unknown as Record<string | symbol, unknown>)[prop] : anyNode()),
        set: (target, prop, value) => {
            (target as unknown as Record<string | symbol, unknown>)[prop] = value;
            return true;
        },
        apply: () => anyNode(),
    });

const made: { resume: ReturnType<typeof vi.fn> }[] = [];

class FakeAudioContext {
    state = 'suspended';
    sampleRate = 48000;
    currentTime = 0;
    destination = {};
    resume = vi.fn(() => Promise.resolve());
    close = vi.fn(() => Promise.resolve());
    constructor() {
        made.push(this);
        return new Proxy(this, { get: (target, prop) => (prop in target ? (target as unknown as Record<string | symbol, unknown>)[prop] : anyNode()) });
    }
}

const ITEMS: CatalogItem[] = [
    { id: 'alex/deploy', name: 'deploy', kind: 'skill', publisher: 'alex', latest: '1.0', card: { title: 'Deploy Runner' }, versions: [] },
    { id: 'zoe/dusk', name: 'dusk', kind: 'theme', publisher: 'zoe', latest: '1.0', card: { title: 'Dusk' }, versions: [] },
] as unknown as CatalogItem[];

const LEDGER = [
    { install_id: 'i1', item_id: 'alex/deploy', name: 'Deploy Runner', scope: 'global', installed_at: '2026-10-16T10:00:00Z', updated_at: '2026-10-16T10:00:00Z' },
] as unknown as InstalledItem[];

/** A catalog host that answers the reads the board makes and refuses the rest. */
function hostFor(): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-10-16' }, items: ITEMS, untrusted: [] }),
        refreshIndex: refuse,
        opened: () => Promise.resolve({}),
        listInstalled: () => Promise.resolve({ items: LEDGER }),
        catalogSession: () => Promise.resolve({ signed_in: true, login: 'harbor' }),
        itemInstalls: refuse,
        installCounts: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

/** Let every microtask and every timer shorter than `ms` settle. */
const settle = (ms = 0): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const press = (code: string, key: string, altKey = false): void => {
    document.body.dispatchEvent(new KeyboardEvent('keydown', { code, key, altKey, bubbles: true, cancelable: true }));
};

let acts: ReturnType<typeof mount> | null = null;
let elite: HTMLElement;

beforeEach(() => {
    made.length = 0;
    vi.stubGlobal('AudioContext', FakeAudioContext);
    elite = document.createElement('div');
    elite.id = 'elite-screen';
    document.body.appendChild(elite);
});

afterEach(async () => {
    const { closeEliteScreen } = await import('./elite-host');
    closeEliteScreen();
    if (acts) unmount(acts);
    acts = null;
    unmountPanel('elite-screen');
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

describe('Elite Access entry', () => {
    test('the modem handshake is 8.4 s and has no digital-impairment stage', async () => {
        const Modem = await import('./engine/modem');
        expect(Modem.DURATION).toBeCloseTo(8.4, 5);
        expect(Modem.STAGES[Modem.STAGES.length - 1]!.t1).toBeCloseTo(8.4, 5);
        expect(Modem.STAGES.map((s) => s.id)).not.toContain('dil');
    });

    test('the button opens the boot stage, the sound starts inside the click, a key skips and the next key reaches the header', async () => {
        const { ensurePanel } = await import('../mount');
        const EliteScreen = (await import('./EliteScreen.svelte')).default;
        const WarezMenu = (await import('../catalog/menu/WarezMenu.svelte')).default;
        ensurePanel('elite-screen', EliteScreen as never, { host: hostFor(), t } as never);

        const bar = document.createElement('div');
        document.body.appendChild(bar);
        const sources = { storeTotal: 0, storeNewest: 0, storeUpdates: 0, storeByKind: {}, storeItems: [], installed: { skill: [], theme: [], mod: [], plugin: [] }, flagged: [], needs: [] };
        acts = mount(WarezMenu, { target: bar, props: { sources, node: { scope: 'store', page: 'everything' }, onNavigate: () => {}, t } as never });
        const button = bar.querySelector<HTMLButtonElement>('#warez-elite-open');
        expect(button?.textContent?.trim()).toBe('\u03c0');
        expect(button?.title).toBe('ELITE ACCESS');
        expect(button?.getAttribute('aria-label')).toBe('ELITE ACCESS');
        expect(document.body.textContent).not.toContain('[ELITE ACCESS]');
        expect(elite.querySelector('.elite')).toBeNull();

        button!.click();

        expect(elite.querySelector('.elite')).not.toBeNull();
        expect(made).toHaveLength(1);
        expect(made[0]!.resume).toHaveBeenCalled();
        const stage = elite.querySelector<HTMLElement>('.elite-stage')!;
        expect(stage.hidden).toBe(false);
        expect(elite.querySelector<HTMLElement>('.boot-dial')!.hidden).toBe(false);
        await settle(150);
        expect(elite.querySelector('.boot-dial')!.textContent).toContain('ATZ');

        press('Space', ' ');
        await settle();
        expect(stage.hidden).toBe(true);
        expect(elite.querySelector<HTMLInputElement>('#hd-in')!.value).toBe('');

        press('KeyA', 'a');
        await settle();
        expect(elite.querySelector<HTMLInputElement>('#hd-in')!.value).toBe('a');
        expect(elite.querySelector('.hd-last')!.textContent).toBe('last: a all files');

        await settle(50);
        const list = elite.querySelector('.fa-list')!;
        const stray = (el: Element): string[] => Array.from(el.childNodes).filter((n) => n.nodeType === Node.TEXT_NODE && n.textContent !== '').map((n) => JSON.stringify(n.textContent));
        expect(stray(list)).toEqual([]);
        expect(stray(list.parentElement!)).toEqual([]);

        const logo = elite.querySelector('.m1h-logo')!;
        const drawn = logo.textContent!.length;
        expect(drawn).toBeGreaterThan(100);
        press('KeyL', 'l', true);
        expect(logo.textContent!.length).toBeLessThan(drawn);
    });

    test('space on a focused button presses it instead of tagging, and the view has no sound control and no id line', async () => {
        const { ensurePanel } = await import('../mount');
        const EliteScreen = (await import('./EliteScreen.svelte')).default;
        const { openEliteScreen } = await import('./elite-host');
        ensurePanel('elite-screen', EliteScreen as never, { host: hostFor(), t } as never);
        openEliteScreen({ direct: true });
        await settle(150);
        await vi.waitFor(() => expect(elite.querySelector('.fa-row')).not.toBeNull());
        const tagged = (): number => elite.querySelectorAll('.fa-row.tagged').length;

        expect(elite.querySelector('[data-opt="sound"]')).toBeNull();
        expect(elite.querySelector('.m1h-opt, .dz-chk, .dz-opts')).toBeNull();
        expect(elite.textContent).not.toMatch(/sound (on|off)|modem sound/i);
        const rows = Array.from(elite.querySelectorAll('.fa-row'));
        expect(rows.length).toBeGreaterThan(0);
        for (const row of rows) expect(row.textContent).not.toMatch(/\w+\/\w+/);
        expect(rows[0]!.querySelectorAll('.fa-l')).toHaveLength(2);

        const button = elite.querySelector<HTMLButtonElement>('.m1h-cline')!;
        button.focus();
        button.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space', key: ' ', bubbles: true, cancelable: true }));
        expect(tagged()).toBe(0);
    });

    test('the modem sound plays on the open with no preference set and with the old stored choice off, and Alt+M does nothing', async () => {
        const { ensurePanel } = await import('../mount');
        const EliteScreen = (await import('./EliteScreen.svelte')).default;
        const { openEliteScreen } = await import('./elite-host');
        vi.stubGlobal('Preferences', { status: () => 'hydrated', HYDRATED: 'hydrated' });
        vi.stubGlobal('PreferenceBridge', { read: (field: string) => (field === 'warez_modem_sound' ? false : null), write: () => Promise.resolve({}) });
        ensurePanel('elite-screen', EliteScreen as never, { host: hostFor(), t } as never);
        expect(openEliteScreen()).toBe(true);
        expect(made).toHaveLength(1);
        expect(made[0]!.resume).toHaveBeenCalled();
        const Modem = await import('./engine/modem');
        expect(Modem.enabled()).toBe(true);
        press('KeyM', 'm', true);
        await settle();
        expect(Modem.enabled()).toBe(true);
        expect(elite.querySelector('[data-opt="sound"]')).toBeNull();
    });
});
