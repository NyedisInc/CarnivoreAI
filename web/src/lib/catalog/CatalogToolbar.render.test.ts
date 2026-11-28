/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import CatalogToolbar from './CatalogToolbar.svelte';
import type { CatalogFilters } from './filter';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const NONE = { kind: null, installed: false, available: false, updates: false } as unknown as CatalogFilters;

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function draw(filters: CatalogFilters): CatalogFilters[] {
    const seen: CatalogFilters[] = [];
    handle = mount(CatalogToolbar, { target: document.body, props: { filters, kinds: ['skill', 'plugin'], t, onFilters: (next: CatalogFilters) => seen.push(next) } });
    flushSync();
    return seen;
}

function radio(group: string, text: string): HTMLButtonElement {
    const found = [...document.querySelectorAll<HTMLButtonElement>(`[role="radiogroup"][aria-label="${group}"] [role="radio"]`)].find((b) => b.textContent?.includes(text));
    if (!found) throw new Error(`no ${group} radio "${text}"`);
    return found;
}

describe('catalog toolbar on the base Segmented', () => {
    test('both groups are base segmented radio groups, not hand-built buttons', () => {
        draw(NONE);
        expect(document.querySelectorAll('.oc-segmented[role="radiogroup"]')).toHaveLength(2);
        expect(document.querySelectorAll('.oc-segmented__caption')).toHaveLength(2);
        expect(document.querySelectorAll('[data-kind] .kind-mark')).toHaveLength(2);
        expect(document.querySelector('.oc-seg__item')).toBeNull();
        expect(document.querySelector('[data-kind="skill"]')).not.toBeNull();
    });

    test('a kind press narrows to it, and "every kind" clears it', () => {
        const seen = draw({ ...NONE, kind: 'skill' } as CatalogFilters);
        radio(t('warez.group.kind'), 'plugin').click();
        expect(seen.at(-1)?.kind).toBe('plugin');
        radio(t('warez.group.kind'), t(BROWSE_KEYS.kindChipAll)).click();
        expect(seen.at(-1)?.kind).toBeNull();
    });

    test('a state press sets it, and pressing the lit one again clears it', () => {
        const seen = draw(NONE);
        const group = t('warez.group.state');
        const installed = [...document.querySelectorAll<HTMLButtonElement>(`[aria-label="${group}"] [role="radio"]`)][0]!;
        installed.click();
        expect(seen.at(-1)?.installed).toBe(true);
        handle && unmount(handle);
        document.body.innerHTML = '';
        const again = draw({ ...NONE, installed: true } as CatalogFilters);
        [...document.querySelectorAll<HTMLButtonElement>(`[aria-label="${group}"] [role="radio"]`)][0]!.click();
        expect(again.at(-1)?.installed).toBe(false);
    });
});
