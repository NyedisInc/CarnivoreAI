/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import DeepSearchScopePanel from './DeepSearchScopePanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { IndexScope } from '../deepsearch/scope-api';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

async function render(start: IndexScope, failure: string | null = null) {
    const saved: IndexScope[] = [];
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(DeepSearchScopePanel, {
        target,
        props: { load: async () => start, save: async (s: IndexScope) => { saved.push(s); return failure; } },
    }));
    await settle();
    return { root: target, saved };
}

const cards = (root: HTMLElement) => [...root.querySelectorAll<HTMLInputElement>('input[type="radio"]')];

describe('DeepSearchScopePanel', () => {
    test('lists the three scopes with the one in force checked', async () => {
        const { root } = await render('all');
        expect(cards(root).map((c) => String(c.checked))).toEqual(['false', 'false', 'true']);
    });

    test('clicking a scope saves it and checks it', async () => {
        const { root, saved } = await render('all');
        cards(root)[0]?.click();
        await settle();
        expect(saved).toEqual(['human']);
        expect(cards(root).map((c) => String(c.checked))).toEqual(['true', 'false', 'false']);
    });

    test('a refused save is said and the choice does not move', async () => {
        const { root } = await render('all', 'config.json cannot be written');
        cards(root)[1]?.click();
        await settle();
        expect(root.querySelector('[role="alert"]')!.textContent).toContain('cannot be written');
        expect(cards(root).map((c) => String(c.checked))).toEqual(['false', 'false', 'true']);
    });
});
