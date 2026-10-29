/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import RoutingPanel from './RoutingPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Fetcher } from './api';

setLocale('en');

const HREF = '#settings/log_processor/cplugs?highlight=log_processor.cplugs.example';

function fetcherWith(overridden: boolean): Fetcher {
    const owner = { id: 'log_processor', label_key: 'settings.section.log_processor', href: HREF, control: 'log_processor.cplugs.example', overridden };
    const owned = (id: string, label_key: string) => ({ id, capability: 'chat', label_key, description_key: null, target: null, group: null, owner, hidden: !overridden });
    return (async (path: string) => {
        if (path === '/ai/presets') return { presets: [] };
        if (path === '/ai/connections') return { revision: 1, connections: [], defaults: {}, features: {} };
        if (path === '/ai/features') return { features: [
            owned('example.feature.a', 'ai.feature.pack_placement'),
            owned('example.feature.b', 'ai.feature.pack_placement'),
            { id: 'pack.placement.example', capability: 'chat', label_key: 'ai.feature.pack_placement', description_key: null, target: null, group: 'summary', owner: null, hidden: false },
        ] };
        if (path === '/ledger/accounts') return { accounts: [] };
        return {};
    }) as unknown as Fetcher;
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
});

async function render(fetcher: Fetcher): Promise<void> {
    mounted.push(mount(RoutingPanel, { target: document.body, props: { fetcher } }));
    for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

const names = (sel: string): string[] => [...document.body.querySelectorAll(`${sel} [data-ai-route-name]`)].map((el) => el.getAttribute('data-ai-route-name') ?? '');

describe('ai routing add-on features', () => {
    test('override off: the owned features are hidden and no add-ons heading shows', async () => {
        await render(fetcherWith(false));
        expect(names('[data-ai="features"]')).toHaveLength(1);
        expect(document.body.querySelector('[data-ai="addons-head"]')).toBeNull();
        expect(document.body.querySelector('[data-ai="addon-features"]')).toBeNull();
        expect(document.body.querySelector('[data-ai="route-owner-link"]')).toBeNull();
    });

    test('override on: the fold is closed by default and counts the overrides; opening it lists them, each name a link to the switch', async () => {
        await render(fetcherWith(true));
        expect(names('[data-ai="features"]')).toHaveLength(1);
        const head = document.body.querySelector<HTMLButtonElement>('[data-ai="addons-head"]')!;
        expect(head.textContent).toContain('plugin overrides (2)');
        expect(head.textContent).toContain('(overridden in add-on settings)');
        expect(head.getAttribute('aria-expanded')).toBe('false');
        expect(document.body.querySelector('[data-ai="addon-features"]')).toBeNull();
        head.click();
        flushSync();
        expect(head.getAttribute('aria-expanded')).toBe('true');
        head.click();
        flushSync();
        expect(document.body.querySelector('[data-ai="addon-features"]')).toBeNull();
        head.click();
        flushSync();
        expect(names('[data-ai="addon-features"]')).toHaveLength(2);
        const links = [...document.body.querySelectorAll<HTMLAnchorElement>('[data-ai="addon-features"] [data-ai="route-owner-link"]')];
        expect(links).toHaveLength(2);
        for (const link of links) expect(link.getAttribute('href')).toBe(HREF);
        expect(document.body.querySelector('[data-ai="features"] [data-ai="route-owner-link"]')).toBeNull();
    });
});
