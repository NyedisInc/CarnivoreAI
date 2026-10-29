/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../help/HelpFeatures.svelte', () => ({ default: function HelpFeaturesStub(): void {} }));

import DocsGuide from './DocsGuide.svelte';
import GuideBody from '../user-guide/GuideBody.svelte';
import { GUIDE_SECTIONS } from '../user-guide/guide-content';
import { filterSections } from '../user-guide/guide-search';
import { parseGuide } from '../user-guide/guide-parse';
import { docsSectionOf, DOCS_TOP_SECTION, DOCS_WRAPPERS_HASH } from './docs-sections';
import { STATUS_LABELS } from '../status-dot';
import { createOverlayHost } from '../manager-frame/overlay-host';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    delete (window as unknown as { SidebarHelp?: unknown }).SidebarHelp;
    window.location.hash = '';
});

function render(query = ''): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(DocsGuide, { target, props: { t, query } });
    flushSync();
    return target;
}

const idsOf = (target: HTMLElement): (string | undefined)[] =>
    [...target.querySelectorAll('[data-docs-section]')].map((n) => (n as HTMLElement).dataset.docsSection);

describe('the documentation guide', () => {
    test('every markdown section is drawn in file order with its title', () => {
        const target = render();
        expect(idsOf(target)).toEqual(GUIDE_SECTIONS.map((s) => s.id));
        expect(GUIDE_SECTIONS.map((s) => s.id)).toEqual(expect.arrayContaining(['start', 'sidebar', 'marks', 'wrappers', 'keys', 'index']));
        for (const section of GUIDE_SECTIONS) {
            expect(section.title, section.id).not.toBe('');
            expect(section.doc.errors, section.id).toEqual([]);
        }
        expect(target.textContent).not.toMatch(/\bdocs\.[a-z]+\.[a-z.0-9]+/);
    });

    test('the contents link each section as #docs/<id>, in the same order', () => {
        const target = render();
        const links = [...target.querySelectorAll('[data-docs-toc-link]')] as HTMLAnchorElement[];
        expect(links.map((a) => docsSectionOf(a.getAttribute('href')))).toEqual(GUIDE_SECTIONS.map((s) => s.id));
    });

    test('search is a plain, case-insensitive substring over sections', () => {
        expect(filterSections('COFFEE CUP', GUIDE_SECTIONS).map((s) => s.id)).toEqual(['sidebar']);
        expect(filterSections('   ', GUIDE_SECTIONS).length).toBe(GUIDE_SECTIONS.length);
        const target = render('pace marker');
        expect(idsOf(target)).toEqual(['accounts']);
        expect(target.querySelectorAll('[data-docs-toc-link]').length).toBe(1);
    });

    test('a search nothing matches says so and draws no section', () => {
        const target = render('zzzqqq');
        expect(target.querySelector('[data-docs-none]')).not.toBeNull();
        expect(target.querySelector('[data-docs-section]')).toBeNull();
    });
});

describe('the markdown body', () => {
    function body(source: string): HTMLElement {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(GuideBody, { target, props: { blocks: parseGuide(source).blocks, t } });
        flushSync();
        return target;
    }

    test('HTML typed in a guide file is text, never elements', () => {
        const target = body('# t\n\n<script>window.pwned = 1</script> <img src=x onerror="window.pwned = 1"> [x](javascript:window.pwned=1)');
        expect(target.querySelector('script, img')).toBeNull();
        expect(target.textContent).toContain('<script>window.pwned = 1</script>');
        expect(target.querySelector('a')).toBeNull();
        expect((window as unknown as { pwned?: number }).pwned).toBeUndefined();
    });

    test('a fragment link stays in the tab and sets the location hash', () => {
        const target = body('# t\n\n[open it](#docs/wrappers) and [out](https://example.com)');
        const [inside, outside] = [...target.querySelectorAll('a')] as HTMLAnchorElement[];
        expect(inside?.getAttribute('target')).toBeNull();
        expect(outside?.getAttribute('target')).toBe('_blank');
        inside?.click();
        expect(window.location.hash).toBe('#docs/wrappers');
    });

    test('::open-legend is a button that opens the sidebar legend panel', () => {
        const opened: Array<Element | null> = [];
        (window as unknown as { SidebarHelp?: unknown }).SidebarHelp = { open: (a: Element | null) => opened.push(a) };
        const target = body('# t\n::open-legend');
        (target.querySelector('[data-docs-marks-open]') as HTMLElement).click();
        expect(opened.length).toBe(1);
    });
});

describe('the launch profiles section', () => {
    test('explains the pick order and the arguments, with four samples and no secret', () => {
        const section = GUIDE_SECTIONS.find((s) => s.id === 'wrappers');
        expect(section).toBeDefined();
        const target = render();
        const node = target.querySelector('[data-docs-section="wrappers"]') as HTMLElement;
        expect(node.id).toBe('docs-wrappers');
        expect(node.querySelectorAll('ol li').length).toBeGreaterThanOrEqual(2);
        expect(node.textContent).toContain('"$@"');
        const scripts = [...node.querySelectorAll('pre')].map((p) => p.textContent ?? '');
        expect(scripts.length).toBe(4);
        for (const script of scripts) {
            expect(script.length).toBeGreaterThan(20);
            expect(script).not.toMatch(/sk-[A-Za-z0-9]{8,}|Bearer |password=|token=["'][A-Za-z0-9]/i);
        }
    });
});

describe('the #docs/<section> deep link', () => {
    test('is the docs page\'s fragment and names the section', () => {
        const host = createOverlayHost('docs-screen', DocsGuide as never, '#docs');
        expect(host.isHash('#docs')).toBe(true);
        expect(host.isHash(DOCS_WRAPPERS_HASH)).toBe(true);
        expect(host.isHash('#docsfoo')).toBe(false);
        expect(docsSectionOf(DOCS_WRAPPERS_HASH)).toBe('wrappers');
        expect(docsSectionOf('#docs')).toBeNull();
        expect(docsSectionOf('#docs/../x')).toBeNull();
        expect(docsSectionOf('#docs/marks')).toBe('marks');
    });
});

describe('the status-light legend at the top', () => {
    const EIGHT = ['question', 'notice', 'working', 'working_subagent', 'finished_unread', 'idle', 'dead', 'unknown'];

    test('leads the page: the lights section comes before the contents and every other section', () => {
        const target = render();
        const first = target.querySelector('[data-docs-section]') as HTMLElement;
        expect(first.dataset.docsSection).toBe(DOCS_TOP_SECTION);
        const toc = target.querySelector('[data-docs-toc]') as HTMLElement;
        expect(first.compareDocumentPosition(toc) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(idsOf(target)[0]).toBe('lights');
        expect(new Set(idsOf(target)).size).toBe(idsOf(target).length);
    });

    test('draws the eight states once each, as the real status light with its own label', () => {
        const target = render();
        const rows = [...target.querySelectorAll('[data-light-state]')] as HTMLElement[];
        expect(rows.map((r) => r.dataset.lightState).sort()).toEqual([...EIGHT].sort());
        for (const row of rows) {
            const state = row.dataset.lightState as string;
            const led = row.querySelector('.status-led') as HTMLElement;
            expect(led, state).not.toBeNull();
            expect(led.getAttribute('title'), state).toBe(STATUS_LABELS[state]);
            expect(led.dataset.inner, state).toBeTruthy();
            expect(row.textContent).toContain(STATUS_LABELS[state] as string);
        }
        const hues = new Set(rows.map((r) => r.querySelector('.lights__hue')?.textContent));
        expect([...hues].sort()).toEqual(['gray', 'green', 'light blue', 'red', 'yellow']);
    });

    test('the states are the ones docs/session-status.md defines', () => {
        const doc = readFileSync(resolve(process.cwd(), '../docs/session-status.md'), 'utf8');
        for (const state of EIGHT) expect(doc, state).toContain(`| \`${state}\` |`);
    });

    test('is a grid of ~220px cells, so several fit a row on desktop and one on a phone', () => {
        const source = readFileSync(resolve(process.cwd(), 'src/lib/user-guide/LightsLegend.svelte'), 'utf8');
        expect(source).toMatch(/grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(220px,\s*1fr\)\)/);
    });
});
