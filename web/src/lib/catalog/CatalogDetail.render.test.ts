/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import CatalogDetail from './CatalogDetail.svelte';
import { browserCatalogHost } from './catalog';
import { cardView } from './card';
import { RATINGS_SECTION_ID } from './item-feedback';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogItem } from './types';
import { paletteOf } from './theme-palettes';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const RATED = {
    item_id: 'x', count: 2, average: 4.5,
    histogram: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 1 },
    reviews: [
        { login: 'ann', stars: 5, text: 'works well', updated_at: 1_790_993_383, author: 'ann', publisher: false, review_ref: 'r1' },
        { login: 'bob', stars: 4, text: '', updated_at: 1_790_993_400, author: 'bob', publisher: false, review_ref: 'r2' },
    ],
};

function plantApi(): void {
    const answers: Record<string, unknown> = {
        getCatalogItem: { item: null },
        getCatalogItemRatings: RATED,
        getCatalogSession: { signed_in: false, login: null },
        getCatalogComments: { comments: [], cursor: null },
        getCatalogItemInstalls: { item_id: 'x', count: 0, by_version: {} },
    };
    (window as unknown as { API: unknown }).API = new Proxy({}, {
        get: (_t, name: string) => () =>
            name in answers ? Promise.resolve(answers[name]) : Promise.reject(new Error('not planted: ' + name)),
    });
}

let handle: Record<string, unknown> | null = null;

function paint(kind: 'plugin' | 'skill' | 'theme' | 'mod', id = `example-owner/${kind}-one`, extra: Record<string, unknown> = {}, untrusted = false, itemExtra: Record<string, unknown> = {}): void {
    const item = {
        id, kind, publisher: 'example-owner', latest: '1.0.0',
        card: { title: `${kind} one`, brief: 'does a thing' },
        versions: [{ version: '1.0.0' }],
        ...itemExtra,
    } as unknown as CatalogItem;
    const target = document.createElement('div');
    document.body.appendChild(target);
    handle = mount(CatalogDetail, {
        target,
        props: {
            card: cardView(item, untrusted), item, installed: [], rowState: { kind: 'idle' },
            host: browserCatalogHost(), t, onInstall: () => {}, onLedgerChange: () => {}, onClose: () => {},
                    ...extra,
        } as never,
    }) as never;
}

const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));

beforeEach(plantApi);
afterEach(() => {
    if (handle) unmount(handle as never);
    handle = null;
    document.body.innerHTML = '';
    delete (window as unknown as { API?: unknown }).API;
});

const after = (a: Element, b: Element) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe.each(['plugin', 'skill'] as const)('a %s detail pane', (kind) => {
    test('top down: bar, band, hero, title with its kind mark, brief, acts, ratings, provenance last', async () => {
        paint(kind);
        await settle();
        const pane = document.querySelector('.detail') as HTMLElement;
        const band = pane.querySelector('[data-detail-band]') as HTMLElement;
        const hero = pane.querySelector('.detail__hero') as HTMLElement;
        const title = pane.querySelector('.detail__title') as HTMLElement;
        const brief = pane.querySelector('.detail__brief') as HTMLElement;
        const acts = pane.querySelector('[data-detail-sec="acts"]') as HTMLElement;
        const ratings = document.getElementById(RATINGS_SECTION_ID) as HTMLElement;
        (pane.querySelector('[data-detail-advanced]') as HTMLElement).click();
        await settle();
        const prov = pane.querySelector('[data-detail-provenance]') as HTMLElement;
        expect(band.className).toContain(`kind-band--${kind}`);
        expect(hero.querySelector('[data-detail-banner]')).not.toBeNull();
        expect(title.textContent).toBe(`${kind} one`);
        expect(title.firstElementChild?.className).toContain(`kind-mark--${kind}`);
        expect(pane.querySelector('.detail__sub')?.textContent).not.toContain(`example-owner/${kind}-one`);
        for (const [a, b] of [[band, hero], [hero, title], [title, brief], [brief, acts], [acts, ratings], [ratings, prov]]) {
            expect(after(a as Element, b as Element)).toBe(true);
        }
        expect(pane.querySelector('[data-detail-sec="trust"]')).toBeNull();
        expect(pane.lastElementChild?.contains(prov)).toBe(true);
        expect(pane.querySelector('[data-ratings-link]')).toBeNull();
    });

    test('header is laid over the hero: title+author top left, rating+comments top right, X closes, no back button', async () => {
        let closed = 0;
        paint(kind, `example-owner/${kind}-one`, { onClose: () => { closed += 1; } });
        await settle();
        const hero = document.querySelector('[data-detail-hero]') as HTMLElement;
        const tl = hero.querySelector('[data-detail-ov="tl"]') as HTMLElement;
        const tr = hero.querySelector('[data-detail-ov="tr"]') as HTMLElement;
        expect(tl.querySelector('.detail__title')?.textContent).toBe(`${kind} one`);
        expect(tl.querySelector('.detail__sub')?.textContent).toContain('by example-owner');
        expect(tr.querySelector('[data-detail-rating]')?.textContent).toContain('4.5');
        expect(tr.querySelector('[data-detail-comments]')?.textContent).toBe('1 comment');
        const x = hero.querySelector('[data-detail-close]') as HTMLButtonElement;
        expect(x).not.toBeNull();
        expect(tr.contains(x)).toBe(false);
        x.click();
        expect(closed).toBe(1);
        expect(document.querySelector('[data-detail-back]')).toBeNull();
        expect(document.body.textContent).not.toContain('back to the list');
    });

    test('a rating with words is a comment with its author, and the note icon follows the ratings', async () => {
        paint(kind);
        await settle();
        const ratings = document.getElementById(RATINGS_SECTION_ID) as HTMLElement;
        expect(document.body.textContent).toContain('works well');
        expect(document.body.textContent).toContain('ann');
        expect(after(ratings, document.querySelector('[data-theme-note-open]') as HTMLElement)).toBe(true);
    });
});

describe('the description', () => {
    test('the full description stands in the brief\'s place, with no fold to open', async () => {
        const full = 'does a thing, and here is everything else it does when you run it every day.';
        paint('skill', undefined, {}, false, { fm: { description: full } });
        await settle();
        const pane = document.querySelector('.detail') as HTMLElement;
        expect((pane.querySelector('.detail__brief') as HTMLElement).textContent).toBe(full);
        expect(pane.querySelectorAll('.detail__brief')).toHaveLength(1);
        expect(pane.querySelector('[data-detail-sec="brief"] details')).toBeNull();
    });
});

describe('the advanced link', () => {
    test('works with, installed where, review, grade, files and installs stay out until it is pressed', async () => {
        paint('skill');
        await settle();
        const pane = document.querySelector('.detail') as HTMLElement;
        const link = pane.querySelector('[data-detail-advanced]') as HTMLButtonElement;
        expect(link.getAttribute('aria-expanded')).toBe('false');
        expect(pane.querySelector('[data-detail-advanced-body]')).toBeNull();
        expect(pane.querySelector('[data-detail-provenance]')).toBeNull();
        expect(pane.textContent).not.toContain(t('skill.installs.none'));
        expect(pane.textContent).not.toContain(t('skill.grade.absent'));
        link.click();
        await settle();
        expect(link.getAttribute('aria-expanded')).toBe('true');
        const body = pane.querySelector('[data-detail-advanced-body]') as HTMLElement;
        expect(body.querySelector('[data-detail-provenance]')).not.toBeNull();
        expect(body.textContent).toContain(t('skill.grade.absent'));
        link.click();
        await settle();
        expect(pane.querySelector('[data-detail-advanced-body]')).toBeNull();
    });
});

describe('the hero by kind', () => {
    test('a theme with a palette is drawn by the themes page inspector, with the store acts and no second ratings block', async () => {
        const palette = paletteOf('example-owner/theme-one', {
            digest: 'a'.repeat(64), version: '1.0.0', cssVars: { '--color-bg': '#112233' }, xterm: {}, ascii: false,
        });
        paint('theme', 'example-owner/theme-one', { palette });
        await settle();
        expect(document.querySelector('.detail__hero')).toBeNull();
        const tins = document.querySelector('[data-inspector="example-owner/theme-one"]') as HTMLElement;
        expect(tins.querySelector('[data-preview-size="large"]')).not.toBeNull();
        expect(tins.querySelectorAll('.tins-ui li').length).toBe(8);
        expect(tins.querySelector('[data-theme-apply], [data-theme-export], [data-theme-install-note]')).toBeNull();
        expect(document.querySelector('[data-detail-close]')).not.toBeNull();
        expect(document.querySelectorAll('.tfb, [data-item-feedback]').length).toBeLessThanOrEqual(1);
    });

    test('a theme with no palette draws the letter slab and no swatches', async () => {
        paint('theme', 'example-owner/theme-one');
        await settle();
        expect(document.querySelector('.detail__hero--plate')).toBeNull();
        expect(document.querySelector('.detail__letter')?.getAttribute('data-glyph')).toBe('T');
        expect(document.querySelector('.swatch-row')).toBeNull();
    });

    test('a mod with no art draws the plug glyph, not a letter', async () => {
        paint('mod', 'example-owner/mod-one');
        await settle();
        expect(document.querySelector('.detail__letter')).toBeNull();
        expect(document.querySelector('[data-detail-banner] svg')).not.toBeNull();
    });
});

describe('an item with no id', () => {
    test('reads no ratings', async () => {
        paint('plugin', '');
        await settle();
        expect(document.querySelector('[data-ratings-link]')).toBeNull();
    });
});
