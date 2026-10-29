/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { panelInstance, unmountPanel } from '../mount';
import type { CatalogHost } from './catalog';
import { CATALOG_SCREEN_CONTAINER } from './screen-host';
import { isWarezHash } from './warez-host';
import type { CatalogItem, InstalledItem } from './types';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

/** The repo root, from this file. */
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ITEMS: CatalogItem[] = [
    {
        id: 'alex/deploy',
        name: 'deploy',
        publisher: 'alex',
        latest: '1.0',
        card: { title: 'Deploy Runner', brief: 'ships a build', tags: ['cli'] },
        versions: [
            {
                v: '1.0',
                scripts: 2,
                size: 4096,
                files: 6,
                digest: 'abcdef0123456789',
                review: {
                    status: 'reviewed',
                    summary: 'it runs a shell command',
                    warnings: [{ kind: 'shell_exec', detail: 'calls bash' }],
                },
            },
        ],
    },
    {
        id: 'zoe/audit',
        name: 'audit',
        publisher: 'zoe',
        latest: '3.1',
        card: { title: 'Security Audit', brief: 'reviews a repo', tags: ['ops'] },
        versions: [{ v: '3.1', review: { status: 'unavailable' } }],
    },
];

const UNTRUSTED: CatalogItem[] = [
    { id: 'mallory/x', name: 'x', publisher: 'mallory', latest: '1', card: { title: 'Unpinned' } },
];

const LEDGER: InstalledItem[] = [
    {
        install_id: 'i1',
        item_id: 'alex/deploy',
        scope: 'global',
        revision: 3,
        version: '0.9',
        update_available: true,
        auto_update: false,
    },
];

function hostFor(
    items: CatalogItem[] = ITEMS,
    untrusted: CatalogItem[] = UNTRUSTED,
    ledger: InstalledItem[] = LEDGER,
    index: Record<string, unknown> = { as_of: '2026-09-15' },
): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index, items, untrusted }),
        refreshIndex: refuse,
        listInstalled: () => Promise.resolve({ items: ledger }),
        previewInstall: refuse,
        install: refuse,
        uninstall: refuse,
        item: (id: string) =>
            Promise.resolve(items.find((entry) => entry.id === id) ?? ({} as CatalogItem)),
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => [],
        oneShot: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

/** Let every microtask and every timer shorter than `ms` settle. */
function settle(ms = 0): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function styleOf(component: string): string {
    const source = readFileSync(
        path.join(ROOT, 'web/src/lib/catalog', component),
        'utf8',
    );
    const start = source.indexOf('<style>');
    return start === -1 ? '' : source.slice(start);
}

type Handle = { show?: (options?: Record<string, unknown>) => void; close?: () => void };

function closeCatalogScreen(): boolean {
    const handle = panelInstance(CATALOG_SCREEN_CONTAINER) as Handle | null;
    if (!handle?.close) return false;
    handle.close();
    return true;
}

function openCatalogScreen(options: Record<string, unknown> = {}): boolean {
    const handle = panelInstance(CATALOG_SCREEN_CONTAINER) as Handle | null;
    if (!handle?.show) return false;
    handle.show(options);
    return true;
}

const unmountCatalogScreen = (): boolean => unmountPanel(CATALOG_SCREEN_CONTAINER);

let container: HTMLElement;

beforeEach(() => {
    localStorage.removeItem('carnivore.pageview.skills');
    container = document.createElement('div');
    container.id = CATALOG_SCREEN_CONTAINER;
    document.body.appendChild(container);
});

afterEach(() => {
    unmountCatalogScreen();
    unmountPanel(CATALOG_SCREEN_CONTAINER);
    document.body.innerHTML = '';
});

/** Mount the screen over the fixture host, open it, and let it settle. */
async function paint(host: CatalogHost = hostFor()): Promise<Record<string, unknown>> {
    const { ensurePanel } = await import('../mount');
    const CatalogScreen = (await import('./CatalogScreen.svelte')).default;
    const handle = ensurePanel(
        CATALOG_SCREEN_CONTAINER,
        CatalogScreen as never,
        { host, t } as never,
    ) as Record<string, unknown>;
    (handle.show as () => void)();
    await settle();
    return handle;
}

function titles(): string[] {
    return [...document.querySelectorAll('.catalog-card__title')].map((node) =>
        (node.textContent ?? '').trim(),
    );
}

async function search(text: string): Promise<void> {
    const box = document.querySelector('.oc-titlebar input[type="search"]') as HTMLInputElement;
    box.value = text;
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await settle(220);
}

async function pressState(label: string): Promise<void> {
    const seg = [...document.querySelectorAll('[data-group="state"] [role="radio"]')].find((node) =>
        (node.textContent ?? '').trim() === label,
    ) as HTMLButtonElement;
    seg.click();
    await settle();
}

describe('the screen reaches the document through one container and no other', () => {
    test('it mounts into #catalog-screen and paints nothing outside it', async () => {
        await paint();
        expect(container.querySelector('.oc-page')).not.toBeNull();
        expect(document.body.children).toHaveLength(1);
    });

    test('mounting does NOT show it: the container stays empty until opened', async () => {
        const { ensurePanel } = await import('../mount');
        const CatalogScreen = (await import('./CatalogScreen.svelte')).default;
        ensurePanel(CATALOG_SCREEN_CONTAINER, CatalogScreen as never, {
            host: hostFor(),
            t,
        } as never);
        await settle();
        expect(container.querySelector('.oc-page')).toBeNull();
    });

    test('the host opens and closes the live instance rather than remounting it', async () => {
        await paint();
        const before = panelInstance(CATALOG_SCREEN_CONTAINER);
        closeCatalogScreen();
        await settle();
        expect(container.querySelector('.oc-page')).toBeNull();
        openCatalogScreen();
        await settle();
        expect(container.querySelector('.oc-page')).not.toBeNull();
        expect(panelInstance(CATALOG_SCREEN_CONTAINER)).toBe(before);
    });

    test('escape does not close it (a page is left by navigating)', async () => {
        await paint();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        await settle();
        expect(container.querySelector('.oc-page')).not.toBeNull();
    });
});

describe('the rows, the search and the filters', () => {
    test('every trusted row and every untrusted row is listed', async () => {
        await paint();
        expect(titles()).toEqual(['Deploy Runner', 'Security Audit', 'Unpinned']);
    });

    test('the search narrows over the title, the publisher and a tag', async () => {
        await paint();
        await search('deploy');
        expect(titles()).toEqual(['Deploy Runner']);
        await search('zoe');
        expect(titles()).toEqual(['Security Audit']);
        await search('cli');
        expect(titles()).toEqual(['Deploy Runner']);
    });

    test('nothing matching says the FILTERS emptied it, not the catalog', async () => {
        await paint();
        await search('xyzzy');
        expect(titles()).toEqual([]);
        expect(document.body.textContent).toContain(i18n.t('skills.hub.hl.none'));
        expect(document.body.textContent).toContain(i18n.t('warez.empty.nomatch_detail'));
        expect(document.body.textContent).not.toContain(i18n.t('skill.catalog.empty'));
    });

    test('an EMPTY catalog says something different from a narrow filter', async () => {
        // NEGATIVE CONTROL for
        await paint(hostFor([], [], []));
        expect(document.body.textContent).toContain(i18n.t('skill.catalog.empty'));
        expect(document.body.textContent).not.toContain(i18n.t('skills.hub.hl.none'));
        expect(document.body.textContent).not.toContain(i18n.t('warez.empty.nomatch_detail'));
    });

    test('the installed filter keeps only what the ledger carries', async () => {
        await paint();
        await pressState(i18n.t('skill.filter.installed'));
        expect(titles()).toEqual(['Deploy Runner']);
    });

    test('the updates filter reads the ledger badge', async () => {
        await paint();
        await pressState(i18n.t('warez.state.updates'));
        expect(titles()).toEqual(['Deploy Runner']);
    });

    test('the untrusted group is LISTED by default and is never dropped', async () => {
        await paint();
        expect(titles()).toContain('Unpinned');
        expect(document.body.textContent).toContain(
            i18n.t('skill.catalog.untrusted.heading'),
        );
    });

    test('clearing the filters brings every row back', async () => {
        await paint();
        await search('xyzzy');
        (document.querySelector('.rows__clear') as HTMLButtonElement).click();
        await settle(220);
        expect(titles()).toEqual(['Deploy Runner', 'Security Audit', 'Unpinned']);
    });

    test('there is no footer line: the count lives in the skills page title bar', async () => {
        await paint();
        expect(document.querySelector('.rows__footer')).toBeNull();
    });

    test('the state segments are a radio group, one lit at a time, and pressing updates after installed leaves exactly updates', async () => {
        await paint();
        const seg = (label: string) =>
            [...document.querySelectorAll('[data-group="state"] [role="radio"]')].find(
                (node) => (node.textContent ?? '').trim() === label,
            ) as HTMLButtonElement;
        expect(seg(i18n.t('warez.filter.any')).getAttribute('aria-checked')).toBe('true');
        await pressState(i18n.t('skill.filter.installed'));
        expect(seg(i18n.t('skill.filter.installed')).getAttribute('aria-checked')).toBe('true');
        await pressState(i18n.t('warez.state.updates'));
        expect(seg(i18n.t('skill.filter.installed')).getAttribute('aria-checked')).toBe('false');
        expect(seg(i18n.t('warez.state.updates')).getAttribute('aria-checked')).toBe('true');
        expect(titles()).toEqual(['Deploy Runner']);
    });

    test('the GRID is the default: cards with tile, install-state slot and a pinned footer, and the one header row holds the icon, title, search, sort and view pair', async () => {
        await paint();
        expect(document.querySelector('.rows__list--grid')).not.toBeNull();
        expect(document.querySelectorAll('.catalog-card')).toHaveLength(3);
        expect(document.querySelector('.catalog-row')).toBeNull();
        const card = document.querySelector('.catalog-card') as HTMLElement;
        expect(card).not.toBeNull();
        const strip = document.querySelector('.oc-titlebar') as HTMLElement;
        expect(strip.querySelector('.oc-titlebar__title .oc-titlebar__icon svg[data-icon="floppy-525"]')).not.toBeNull();
        expect(strip.querySelector('.oc-titlebar__title')?.textContent?.trim()).toBe(t('skill.screen.title'));
        expect(strip.querySelector('.wtools input[type="search"]')).not.toBeNull();
        expect(strip.querySelector('.wtools [data-facet="sort"]')).not.toBeNull();
        expect(strip.querySelectorAll('.wtools .oc-page__view .oc-ibtn')).toHaveLength(2);
        expect(strip.querySelector('.warez-act')).not.toBeNull();
        expect(document.querySelector('.oc-page__bar')).toBeNull();
        expect(document.querySelector('.oc-toolbar')).toBeNull();
        expect(document.querySelectorAll('input[type="search"]')).toHaveLength(1);
    });

    test('the toggle swaps to the 28px list rows and the choice is remembered per device', async () => {
        await paint();
        const buttons = document.querySelectorAll('.oc-titlebar .oc-page__view .oc-ibtn');
        (buttons[1] as HTMLButtonElement).click();
        await settle();
        expect(document.querySelectorAll('.catalog-row')).toHaveLength(3);
        expect(document.querySelector('.catalog-card')).toBeNull();
        expect(document.querySelector('.rows__list--grid')).toBeNull();
        expect(localStorage.getItem('carnivore.pageview.skills')).toBe('ledger');
        (buttons[0] as HTMLButtonElement).click();
        await settle();
        expect(document.querySelectorAll('.catalog-card')).toHaveLength(3);
        expect(localStorage.getItem('carnivore.pageview.skills')).toBe('cards');
    });

    test('a remembered list view opens as rows', async () => {
        localStorage.setItem('carnivore.pageview.skills', 'ledger');
        await paint();
        expect(document.querySelectorAll('.catalog-row')).toHaveLength(3);
    });
});

describe('the reading pane', () => {
    /* the reading pane */
    async function open(index = 0): Promise<void> {
        const opener = document.querySelectorAll('.catalog-card__open')[index] as HTMLButtonElement;
        opener.click();
        await settle();
    }

    async function openAdvanced(): Promise<void> {
        (document.querySelector('[data-detail-advanced]') as HTMLButtonElement).click();
        await settle();
    }

    test('it opens on the row that was clicked and shows its facts', async () => {
        await paint();
        await open(0);
        const pane = document.querySelector('.detail');
        expect(pane).not.toBeNull();
        expect(pane?.textContent).toContain('Deploy Runner');
        expect(pane?.textContent).toContain('alex');
        expect(pane?.textContent).toContain('1.0');
    });

    test('a reviewed version shows the summary and EVERY warning kind', async () => {
        await paint();
        await open(0);
        await openAdvanced();
        const review = document.querySelector('.cat-review');
        expect(review?.textContent).toContain('ai reviewed');
        expect(review?.textContent).toContain('it runs a shell command');
        expect(review?.textContent).toContain('runs shell commands');
        expect(review?.textContent).toContain('calls bash');
    });

    test('a review that DID NOT RUN says "no ai review", never "nothing detected"', async () => {
        await paint();
        await open(1);
        await openAdvanced();
        const review = document.querySelector('.cat-review');
        expect(review?.textContent).toContain('no ai review');
        expect((review?.textContent ?? '').toLowerCase()).not.toContain('nothing detected');
        expect((review?.textContent ?? '').toLowerCase()).not.toContain('no warnings');
    });

    test('an ABSENT review block still paints, saying the index carried none', async () => {
        await paint();
        await open(2);
        await openAdvanced();
        const review = document.querySelector('.cat-review');
        expect(review).not.toBeNull();
        expect(review?.textContent).toContain(i18n.t('skill.review.absent'));
    });

    test('an untrusted row is offered NO install control, and says why', async () => {
        await paint();
        await open(2);
        const acts = document.querySelector('.acts');
        expect(acts?.textContent).toContain(i18n.t('skill.card.untrusted'));
        expect(acts?.querySelector('[data-act="install"]')).toBeNull();
    });

    test('an installed global row is offered the auto-update switch', async () => {
        await paint();
        await open(0);
        expect(document.querySelector('.auto__switch')).not.toBeNull();
        expect(document.body.textContent).toContain(i18n.t('skill.update.auto'));
    });

    test('back closes the pane and leaves the list where it was', async () => {
        await paint();
        await open(0);
        (document.querySelector('[data-detail-close]') as HTMLButtonElement).click();
        await settle();
        expect(document.querySelector('.detail')).toBeNull();
        expect(titles()).toHaveLength(3);
    });
});

describe('the phone layout', () => {
    test('below the 767px breakpoint the reading pane REPLACES the list', async () => {
        const css = styleOf('CatalogScreen.svelte');
        expect(css).toContain('max-width: 767px');
        expect(css).toMatch(/screen__body--reading\s*\{\s*grid-template-columns:\s*1fr/);
        expect(css).toMatch(/screen__body--reading\s+:global\(\.rows\)\s*\{\s*display:\s*none/);
    });

    test('a row is 40px, and goes two-line at 56px when its list is narrow', () => {
        const css = styleOf('CatalogCard.svelte');
        expect(css).toMatch(/min-height:\s*40px/);
        expect(css).toMatch(/@container \(width <= 640px\)[\s\S]*min-height:\s*56px/);
        expect(styleOf('CatalogRows.svelte')).toMatch(/container-type:\s*inline-size/);
    });

    test('the search box needs no sticky rule: the title strip sits above the list that scrolls', () => {
        expect(styleOf('WarezTools.svelte')).not.toMatch(/position:\s*sticky/);
        expect(styleOf('CatalogRows.svelte')).toMatch(/overflow:\s*auto/);
    });

    test('every control a thumb has to hit is at least 44px at phone width', () => {
        for (const component of [
            'CatalogToolbar.svelte',
            'ConsentScripts.svelte',
            'OneShotPicker.svelte',
        ]) {
            const css = styleOf(component);
            expect(css, component).toContain('max-width: 767px');
            expect(css, component).toMatch(/min-height:\s*44px/);
        }
    });

    test('at a desktop width the two panes are side by side', async () => {
        await paint();
        const opener = document.querySelector('.catalog-card__open') as HTMLButtonElement;
        opener.click();
        await settle();
        const body = document.querySelector('.screen__body');
        expect(body?.classList.contains('screen__body--reading')).toBe(true);
        expect(document.querySelector('.rows')).not.toBeNull();
        expect(document.querySelector('.screen__detail')).not.toBeNull();
    });
});

describe('the fragment that opens it', () => {
    test('exactly `#catalog` or `#warez`, with or without its hash', () => {
        expect(isWarezHash('#catalog')).toBe(true);
        expect(isWarezHash('catalog')).toBe(true);
        expect(isWarezHash('#warez')).toBe(true);
        expect(isWarezHash('#warez/alex/sme')).toBe(true);
    });

    test('and NOTHING ELSE: a link must not do what its author did not write', () => {
        expect(isWarezHash('#catalogue')).toBe(false);
        expect(isWarezHash('#catalog-foo')).toBe(false);
        expect(isWarezHash('#')).toBe(false);
        expect(isWarezHash('')).toBe(false);
        expect(isWarezHash(null)).toBe(false);
    });
});

describe('the skills screen sign in is one title bar button, and nothing when signed in', () => {
    function sessionHost(signed: boolean): CatalogHost {
        return {
            ...hostFor(),
            catalogSession: () =>
                Promise.resolve({ signed_in: signed, login: signed ? 'ada@example.test' : null, provider: signed ? 'email' : null }),
            signOutOfCatalog: () => Promise.resolve({ signed_in: false, login: null, provider: null }),
        } as unknown as CatalogHost;
    }

    test('signed out shows the sign in act at the foot of the list, not as a strip', async () => {
        await paint(sessionHost(false));
        const cta = document.querySelector('.rows [data-catalog-signin-cta]');
        expect(cta?.textContent?.trim()).toBe(t('skills.hub.signin'));
        expect(document.querySelector('.screen__cta')).toBeNull();
        expect(document.querySelector('.signin')).toBeNull();
        expect(document.querySelector('.esignin')).toBeNull();
    });

    test('signed in shows no call to action and no account panels: they live on the account page', async () => {
        await paint(sessionHost(true));
        expect(document.querySelector('[data-catalog-signin-cta]')).toBeNull();
        expect(document.querySelector('.signin__signout')).toBeNull();
        expect(document.querySelector('.signin')).toBeNull();
        expect(document.querySelector('[data-skills-manage]')).toBeNull();
    });
});

describe('the overlay starts below the sticky app header', () => {
    function overlayRule(): string {
        const css = readFileSync(`${process.cwd()}/src/opscenter/page.css`, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
        const start = css.indexOf('.oc-page {');
        expect(start).toBeGreaterThan(-1);
        return css.slice(start, css.indexOf('}', start));
    }

    test('its top edge is the header offset, not the top of the viewport', () => {
        const rule = overlayRule();
        expect(rule).not.toMatch(/inset:\s*0/);
        expect(rule).toMatch(/top:\s*var\(--overlay-top\)/);
    });

    test('the other three edges still reach the viewport', () => {
        const rule = overlayRule();
        expect(rule).toMatch(/left:\s*0/);
        expect(rule).toMatch(/right:\s*0/);
        expect(rule).toMatch(/bottom:\s*0/);
        expect(rule).toMatch(/z-index:\s*40/);
    });
});

describe('closing it is safe from anywhere, which is what lets a screen switch call it blind', () => {
    test('it closes a live open screen', async () => {
        await paint();
        expect(container.querySelector('.oc-page')).not.toBeNull();
        expect(closeCatalogScreen()).toBe(true);
        await settle();
        expect(container.querySelector('.oc-page')).toBeNull();
    });

    test('a second call on the already closed screen changes nothing and throws nothing', async () => {
        await paint();
        closeCatalogScreen();
        await settle();
        expect(() => closeCatalogScreen()).not.toThrow();
        await settle();
        expect(container.querySelector('.oc-page')).toBeNull();
    });

    test('with nothing mounted it answers false rather than throwing', () => {
        expect(unmountCatalogScreen()).toBe(false);
        expect(() => closeCatalogScreen()).not.toThrow();
        expect(closeCatalogScreen()).toBe(false);
    });

    test('and it reopens afterwards, so closing is not a one-way door', async () => {
        await paint();
        closeCatalogScreen();
        await settle();
        openCatalogScreen();
        await settle();
        expect(container.querySelector('.oc-page')).not.toBeNull();
    });
});

describe('opening on one kind (the themes page opens it on theme)', () => {
    const WITH_THEME: CatalogItem[] = [
        ...ITEMS,
        { ...ITEMS[0], id: 'alex/neon', name: 'neon', kind: 'theme', card: { title: 'Neon Glass', brief: 'a theme', tags: [] } } as CatalogItem,
    ];

    test('show({ kind }) narrows the list to that kind', async () => {
        const handle = await paint(hostFor(WITH_THEME));
        (handle.close as () => void)();
        await settle();
        openCatalogScreen({ kind: 'theme' });
        await settle();
        expect(titles()).toEqual(['Neon Glass']);
    });

    test('a theme opens in the installed inspector width, 380px, with no grip; a skill keeps its grip (Alex, 2026-10-20)', async () => {
        await paint(hostFor(WITH_THEME));
        const open = (title: string) => {
            const card = Array.from(document.querySelectorAll('.catalog-card')).find((c) => c.textContent?.includes(title));
            (card?.querySelector('.catalog-card__open') as HTMLButtonElement).click();
        };
        open('Neon Glass');
        await settle();
        const body = document.querySelector('.screen__body') as HTMLElement;
        expect(body.style.getPropertyValue('--cat-detail-w')).toBe('380px');
        expect(document.querySelector('.screen__detail [data-detail-grip]')).toBeNull();
        open('Deploy Runner');
        await settle();
        expect(document.querySelector('.screen__detail [data-detail-grip]')).not.toBeNull();
    });

    test('NEGATIVE CONTROL: an open with no kind leaves every row listed', async () => {
        await paint(hostFor(WITH_THEME));
        expect(titles()).toContain('Neon Glass');
        expect(titles()).toContain('Deploy Runner');
    });
});

describe('the faceted shelf bar and the status line (issue #1554)', () => {
    const MIXED: CatalogItem[] = [
        ...ITEMS.map((item) => ({ ...item, kind: 'skill', publisher: 'nyedis' })),
        { id: 'nyedis/glow', name: 'glow', kind: 'mod', publisher: 'nyedis', latest: '1.0', card: { title: 'Glow', brief: 'a mod' } },
    ];
    const INDEX = { serial: 36, as_of: '2026-09-15' };

    const stat = () => document.querySelector('.warez-stat')?.textContent?.replace(/\s+/g, ' ').trim();

    test('the filters and publish ride the left rail; search, sort and the view pair ride the title strip (Alex, 2026-10-16 and 2026-10-21)', async () => {
        await paint(hostFor(MIXED, [], [], INDEX));
        const rail = document.querySelector('.cat-rail') as HTMLElement;
        const bar = document.querySelector('.oc-titlebar .wtools') as HTMLElement;
        expect(rail).not.toBeNull();
        expect(rail.querySelector('input')).toBeNull();
        expect(rail.querySelector('[data-group="kind"] .kind-mark--mod')).not.toBeNull();
        expect(rail.querySelector('[data-group="kind"] .cat-rail__label')?.textContent).toBe(t('warez.group.kind'));
        expect(rail.querySelector('[data-group="state"]')).not.toBeNull();
        expect(rail.querySelector('#catalog-submit-open')).not.toBeNull();
        expect(bar.querySelector('.oc-facet:has([data-facet="sort"])')).not.toBeNull();
        expect(bar.querySelector('.oc-page__view')).not.toBeNull();
        expect(bar.querySelector('[data-group], .bar__kind, .bar__flag')).toBeNull();
        expect(document.querySelector('.oc-titlebar #catalog-submit-open')).toBeNull();
        expect(bar.querySelector('[data-facet="risk"]')).toBeNull();
        const mod = rail.querySelector('[data-group="kind"] [data-kind="mod"]') as HTMLElement;
        mod.click();
        await settle();
        expect(rail.querySelector('[data-group="kind"] [data-kind="mod"]')?.getAttribute('aria-checked')).toBe('true');
        expect(titles()).toEqual(['Glow']);
    });

    test('a plain index draws no serial / signer / count line (#1857); no band heading is drawn', async () => {
        await paint(hostFor(MIXED, [], [], INDEX));
        expect(document.querySelector('.warez-stat')).toBeNull();
        expect(document.body.textContent).not.toContain('signed by');
        expect(document.body.textContent).not.toContain(t('warez.hl.new'));
    });

    test('stale, degraded and refused each keep their own wording', async () => {
        await paint(hostFor(MIXED, [], [], { ...INDEX, stale: true }));
        expect(stat()).toContain(t('opscenter.catalog.index_stale'));
        expect(document.querySelector('.warez-stat--stale')).not.toBeNull();
        unmountCatalogScreen();
        await paint(hostFor(MIXED, [], [], { ...INDEX, degraded: true }));
        expect(stat()).toContain(t('opscenter.catalog.index_degraded'));
        unmountCatalogScreen();
        await paint(hostFor(MIXED, [], [], { ...INDEX, refusal: { code: 'signature_invalid' } }));
        expect(stat()).toContain('signature_invalid');
        expect(document.querySelector('.warez-stat--refused')).not.toBeNull();
    });

    test('refresh is a text button in the title strip, publish is not, and ? opens the keys menu', async () => {
        await paint(hostFor(MIXED, [], [], INDEX));
        const strip = document.querySelector('.oc-titlebar') as HTMLElement;
        expect(strip.querySelector('.warez-act')?.textContent?.trim()).toBe(t('skill.catalog.refresh'));
        expect(strip.querySelector('#catalog-submit-open')).toBeNull();
        expect(document.querySelector('.oc-page__bar .bar__refresh')).toBeNull();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));
        await settle();
        expect(document.querySelector('[role="menu"] [data-node^="key:"]')).not.toBeNull();
    });
});
