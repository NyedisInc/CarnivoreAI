/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { beforeAll, describe, expect, test } from 'vitest';

import { pluginGuideEntries } from './plugin-entries';

const GUIDE = path.resolve(process.cwd(), '../client/style-guide/guide.js');

const REGISTRY = {
    sections: [
        { id: 'chrome', title: 'chrome', group: 'components', file: '19-chrome.html' },
        { id: 'dialogs', title: 'dialogs', group: 'components', file: '14-dialogs.html' },
    ],
    excluded: { 'web/src/admin/': 'not an app surface' },
    files: { 'web/src/lib/Core.svelte': { section: 'chrome', classes: ['core-a'] } },
};
const FRAGMENTS: Record<string, string> = { '19-chrome.html': '<p id="core-chrome">core chrome</p>', '14-dialogs.html': '<p>core dialogs</p>' };

beforeAll(async () => {
    document.body.innerHTML = '<div id="sg-toc"></div><div id="sg-content"></div><div id="sg-full-index"></div><ul id="sg-exclusions"></ul>' +
        '<select id="sg-theme-select"></select><span id="sg-theme-status"></span>';
    (window as unknown as { matchMedia: unknown }).matchMedia = () => ({ matches: false });
    globalThis.fetch = (async (url: string) => {
        const name = String(url).split('/').pop() ?? '';
        const body = name === 'registry.json' ? JSON.stringify(REGISTRY) : FRAGMENTS[name];
        return { ok: body !== undefined, status: body === undefined ? 404 : 200, text: async () => body ?? '' };
    }) as unknown as typeof fetch;
    // eslint-disable-next-line no-new-func -- the guide is a classic script served as written; run it as the browser would
    new Function(fs.readFileSync(GUIDE, 'utf8'))();
    for (let i = 0; i < 50 && !(window as { StyleGuideReady?: boolean }).StyleGuideReady; i += 1) await new Promise((r) => setTimeout(r, 5));
});

describe('addPluginEntries', () => {
    test('prose goes before the section coverage block and rows join the coverage and the index', () => {
        const guide = (window as unknown as { StyleGuide: { addPluginEntries: (e: unknown) => void } }).StyleGuide;
        expect((window as { StyleGuideReady?: boolean }).StyleGuideReady).toBe(true);
        guide.addPluginEntries({
            rows: { 'web/src/cplugs/zz/Thing.svelte': { section: 'chrome', classes: ['zz-box'] } },
            prose: [
                { plugin: 'zz', file: '19-chrome.html', html: '<h3 id="zz-h">zz plugin</h3>' },
                { plugin: 'zz', file: '99-missing.html', html: '<p>no section</p>' },
            ],
        });
        const chrome = document.getElementById('chrome')!;
        const kids = [...chrome.children].map((n) => n.className || n.tagName);
        expect(kids.indexOf('sg-plugin-prose')).toBeGreaterThan(-1);
        expect(kids.indexOf('sg-plugin-prose')).toBeLessThan(kids.indexOf('sg-coverage'));
        expect(chrome.querySelector('[data-sg-plugin="zz"] #zz-h')).not.toBeNull();
        expect(document.body.textContent).not.toContain('no section');
        expect(chrome.querySelectorAll('.sg-coverage').length).toBe(1);
        expect(chrome.querySelector('.sg-coverage')!.textContent).toContain('web/src/cplugs/zz/Thing.svelte');
        expect(chrome.querySelector('.sg-coverage')!.textContent).toContain('web/src/lib/Core.svelte');
        expect(document.getElementById('sg-full-index')!.textContent).toContain('.zz-box');
        expect(document.getElementById('sg-exclusions')!.querySelectorAll('li').length).toBe(1);
    });
});

describe('pluginGuideEntries', () => {
    test('finds the shipped slices by folder, each row inside its own plugin folder', () => {
        const { rows, prose } = pluginGuideEntries();
        expect(Object.keys(rows).length).toBeGreaterThan(20);
        expect(Object.keys(rows).every((k) => /^web\/src\/cplugs\/[a-z0-9]+\//.test(k))).toBe(true);
        const plugins = new Set(prose.map((p) => p.plugin));
        for (const id of ['flow', 'reviewboard', 'save', 'share']) expect(plugins.has(id)).toBe(true);
        expect(prose.every((p) => /^\d+[a-z]?-[a-z-]+\.html$/.test(p.file) && p.html.length > 0)).toBe(true);
    });
});
