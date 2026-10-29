/** @vitest-environment jsdom */
import { flushSync, mount, tick, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createI18n } from '../../../../../client/js/i18n/runtime.js';
import type { MenuSources } from './model';
import { nodeHash, parseNodeHash, type MenuNode } from './route';
import WarezMenu from './WarezMenu.svelte';
import { kindIcon } from '../card';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const SOURCES: MenuSources = {
    storeTotal: 25,
    storeNewest: 5,
    storeUpdates: 0,
    storeByKind: { skill: 7, theme: 16, mod: 1, plugin: 1 },
    storeItems: [{ kind: 'skill', id: 'acme/scrooge', title: 'scrooge', installed: false }],
    installed: {
        skill: [{ key: 'sme', title: 'sme', word: 'on' }],
        theme: [{ key: 'green_crt', title: 'Green CRT', word: 'global' }],
        mod: [],
        plugin: [
            { key: 'huddle', title: 'huddle', word: 'on' },
            { key: 'swarm', title: 'swarm', word: 'off' },
        ],
    },
    flagged: [],
    needs: [{ page: 'consent', count: 0 }],
};

let handle: ReturnType<typeof mount> | null = null;
let host: HTMLElement | null = null;
let find = $state('');

function render(sources: MenuSources, onNavigate: (node: MenuNode) => void = () => {}): HTMLElement {
    host = document.createElement('div');
    document.body.append(host);
    handle = mount(WarezMenu, {
        target: host,
        props: { sources, node: { scope: 'store', page: 'everything' } as MenuNode, get find() { return find; }, onNavigate, t },
    });
    flushSync();
    return host;
}

afterEach(() => {
    find = '';
    if (handle) unmount(handle);
    handle = null;
    host?.remove();
    document.body.innerHTML = '';
});

const row = (el: HTMLElement, key: string): HTMLElement => el.querySelector<HTMLElement>(`[data-key="${key}"]`)!;
const count = (el: HTMLElement, key: string): string | undefined => row(el, key).querySelector('[data-count]')?.textContent?.trim();

describe('the warez menu', () => {
    test('groups and counts render, an installed kind lists no items unless searching, a press reports its node', async () => {
        const pressed: MenuNode[] = [];
        const el = render(SOURCES, (node) => pressed.push(node));

        expect([...el.querySelectorAll('[data-group]')].map((g) => g.getAttribute('data-group'))).toEqual(['store', 'installed', 'yours']);
        expect(count(el, 'store/everything')).toBe('25');
        expect(count(el, 'store/newest')).toBe('5');
        expect(count(el, 'store/updates')).toBe('0');
        expect(count(el, 'store/themes')).toBe('16');
        expect(count(el, 'installed/plugins')).toBe('2');
        expect(count(el, 'installed/mods')).toBe('0');

        expect(row(el, 'installed/plugins').hasAttribute('aria-expanded')).toBe(false);
        row(el, 'installed/plugins').click();
        await tick();
        flushSync();
        expect(pressed.at(-1)).toEqual({ scope: 'installed', page: 'kind', kind: 'plugin' });
        expect(el.querySelectorAll('[data-depth="2"]').length).toBe(0);

        expect(el.querySelector('input[type="search"]')).toBeNull();
        find = 'u';
        await tick();
        flushSync();
        const items = [...el.querySelectorAll('[data-depth="2"]')].filter((r) => r.getAttribute('data-key')?.startsWith('installed/'));
        expect(items.map((r) => r.querySelector('.wm__label')?.textContent)).toEqual(['huddle']);
        expect(items.map((r) => r.querySelector('[data-word]')?.textContent)).toEqual(['on']);
        expect(el.querySelectorAll('[data-depth="3"]').length).toBe(0);
        expect(items.every((r) => !r.hasAttribute('aria-expanded'))).toBe(true);

        row(el, 'installed/plugin/huddle').click();
        const node = pressed.at(-1)!;
        expect(node).toEqual({ scope: 'installed', page: 'item', kind: 'plugin', key: 'huddle' });
        expect(nodeHash(node)).toBe('#warez/installed/plugin/huddle');
        expect(parseNodeHash(nodeHash({ ...(node as Extract<MenuNode, { scope: 'installed'; page: 'item' }>), tab: 'settings' }))).toEqual({ ...node, tab: 'settings' });
        expect(parseNodeHash('#warez/ada/neon')).toBeNull();
    });

    test('a changed count tints its row once; a flagged installed entry shows under needs a look', async () => {
        let sources = $state<MenuSources>({ ...SOURCES, flagged: [{ key: 'a/b', title: 'b', word: 'on', kind: 'skill' }], needs: [{ page: 'flagged', count: 1 }] });
        host = document.createElement('div');
        document.body.append(host);
        handle = mount(WarezMenu, { target: host, props: { get sources() { return sources; }, node: { scope: 'store', page: 'everything' } as MenuNode, onNavigate: () => {}, t } });
        flushSync();
        expect(count(host, 'look/flagged')).toBe('1');
        expect(row(host, 'look/flagged').textContent).toContain('flagged installed');
        expect(host.querySelector('.wm__row--tint')).toBeNull();
        sources = { ...sources, storeTotal: 26 };
        await tick();
        flushSync();
        expect(row(host, 'store/everything').classList.contains('wm__row--tint')).toBe(true);
        expect(row(host, 'store/newest').classList.contains('wm__row--tint')).toBe(false);
    });

    test('needs a look is drawn first when it holds something, and the search keeps the matching rows with their parents open', async () => {
        const el = render({ ...SOURCES, needs: [{ page: 'consent', count: 2 }] });
        expect([...el.querySelectorAll('[data-group]')].map((g) => g.getAttribute('data-group'))).toEqual(['look', 'store', 'installed', 'yours']);
        expect(count(el, 'look/consent')).toBe('2');

        find = 'swarm';
        await tick();
        flushSync();
        expect(row(el, 'installed/plugin/swarm')).not.toBeNull();
        expect(el.querySelector('[data-key="installed/plugin/huddle"]')).toBeNull();
        expect(el.querySelector('[data-key="store/themes"]')).toBeNull();
        void vi;
    });

    test('every kind row wears the card kind mark: the KindMark tile in its own kind class with the kind icon', () => {
        const TOKEN: Record<string, string> = { mod: 'rgb(1, 0, 0)', skill: 'rgb(2, 0, 0)', theme: 'rgb(3, 0, 0)', plugin: 'rgb(4, 0, 0)' };
        const src = readFileSync(join(process.cwd(), 'src/lib/catalog/KindMark.svelte'), 'utf8');
        const css = (/<style>([\s\S]*?)<\/style>/.exec(src)?.[1] ?? '').replace(/var\((--[a-z-]+)\)/g, (_a, n: string) => {
            const k = /^--oc-kind-(mod|skill|theme|plugin)$/.exec(n);
            return k ? TOKEN[k[1]!]! : 'rgb(9, 9, 9)';
        });
        const styleEl = document.createElement('style');
        styleEl.textContent = css;
        document.head.appendChild(styleEl);
        const el = render(SOURCES);
        for (const [kind, plural] of [['skill', 'skills'], ['theme', 'themes'], ['mod', 'mods'], ['plugin', 'plugins']] as const) {
            for (const scope of ['store', 'installed']) {
                const mark = row(el, `${scope}/${plural}`).querySelector(`.kind-mark.kind-mark--${kind}.kind-mark--md`);
                expect(mark, `${scope} ${kind}`).not.toBeNull();
                expect(mark!.getAttribute('role')).toBe('img');
                expect(mark!.querySelector(`[data-icon="${kindIcon(kind)}"]`)).not.toBeNull();
                expect(mark!.classList.contains('kind-mark--bare'), `${scope} ${kind} bare`).toBe(true);
                const cs = getComputedStyle(mark!);
                expect(cs.backgroundColor, `${scope} ${kind} fill`).toMatch(/^(transparent|rgba\(0, 0, 0, 0\))$/);
                expect(cs.borderTopWidth, `${scope} ${kind} border`).toBe('0px');
                expect(cs.color, `${scope} ${kind} glyph colour`).toBe(TOKEN[kind]);
            }
        }
        expect(el.querySelector('.wm__glyph svg[viewBox="0 0 14 14"]')).toBeNull();
        styleEl.remove();
    });

    test('the yours group follows installed with one publish row: upload icon, no count, selected on every publish node, present in the phone menu', () => {
        const nodes: MenuNode[] = [
            { scope: 'publish', page: 'tab', tab: 'submissions' },
            { scope: 'publish', page: 'tab', tab: 'themes' },
            { scope: 'publish', page: 'item', tab: 'plugins', location: 'cplug:repo-pulse' },
            { scope: 'publish', page: 'rules' },
        ];
        for (const phone of [false, true]) {
            for (const node of nodes) {
                host = document.createElement('div');
                document.body.append(host);
                const pressed: MenuNode[] = [];
                handle = mount(WarezMenu, { target: host, props: { sources: SOURCES, node, phone, onNavigate: (n: MenuNode) => pressed.push(n), t } });
                flushSync();
                const groups = [...host.querySelectorAll('[data-group]')].map((g) => g.getAttribute('data-group'));
                expect(groups.slice(-2)).toEqual(['installed', 'yours']);
                const publish = row(host, 'publish');
                expect(publish.textContent).toContain('publish yours');
                expect(publish.querySelector('[data-count]')).toBeNull();
                expect(publish.querySelector('.wm__glyph svg path')?.getAttribute('d')).toBe('M12 16V4m-5 5 5-5 5 5M4 20h16');
                expect(publish.getAttribute('aria-selected'), `${phone} ${JSON.stringify(node)}`).toBe('true');
                expect(host.querySelectorAll('[aria-selected="true"]').length).toBe(1);
                publish.click();
                expect(pressed.at(-1)).toEqual({ scope: 'publish', page: 'tab', tab: 'submissions' });
                unmount(handle);
                handle = null;
                host.remove();
            }
        }
    });
});
