/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import InstallSheet from './InstallSheet.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { cardView } from './card';
import type { CatalogHost } from './catalog';
import type { InstallPreview } from './types';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const PREVIEW: InstallPreview = {
    publisher: 'nyedis',
    version: '1.0.0',
    key_id: 'KEYID123',
    pinned: true,
    index_host: 'catalog.example',
    digest: 'DIGESTDIGEST',
    total_bytes: 212888,
    body: '{"colors":{"--color-bg":"#f7f7fa"},"effects":"effects.js"}',
    files: [{ path: 'effects.js', size: 4259 }, { path: 'theme.json', size: 3842 }],
    review: { status: 'reviewed', summary: 'nothing damaging', verdict: 'clean', warnings: [] },
};

function host(): CatalogHost {
    const refuse = () => Promise.reject(new Error('never'));
    return {
        listItems: refuse, refreshIndex: refuse, listInstalled: refuse, install: refuse, uninstall: refuse,
        previewInstall: () => Promise.resolve(PREVIEW),
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

let sheet: Record<string, unknown> | null = null;

async function open(kind: string): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    sheet = mount(InstallSheet, {
        target,
        props: { card: cardView({ id: 'a/b', name: 'calming', kind } as never, false), host: host(), t, close: vi.fn() },
    } as never) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

const text = () => document.body.textContent ?? '';
const advanced = () => document.querySelector<HTMLButtonElement>('.sheet__advanced');

afterEach(() => {
    if (sheet) unmount(sheet as never);
    sheet = null;
    document.body.innerHTML = '';
});

describe('the theme install sheet', () => {
    test('shows only publisher and version, with the detail behind a collapsed advanced button', async () => {
        await open('theme');
        expect(text()).toContain('nyedis');
        expect(text()).toContain('1.0.0');
        for (const gone of ['KEYID123', 'catalog.example', 'DIGESTDIGEST', '212,888', i18n.t('skill.sheet.scope.legend')]) {
            expect(text()).not.toContain(gone);
        }
        expect(text()).not.toContain('installing tells the catalog');
        expect(text()).not.toContain("you confirm you're 16 or older");
        expect(document.querySelector('.sheet__body')).toBeNull();
        expect(document.querySelector('.sheet__swatches, [data-theme-swatches]')).toBeNull();
        const button = advanced()!;
        expect(button.textContent).toBe('advanced...');
        expect(button.getAttribute('aria-expanded')).toBe('false');
        expect(document.querySelector('.sheet__file')).toBeNull();
        expect(text()).not.toContain(i18n.t('skill.review.heading'));
        expect(text()).not.toContain(i18n.t('theme.sheet.effects.heading'));
    });

    test('advanced reveals review, files and script notice in that order, and hides them again', async () => {
        await open('theme');
        advanced()!.click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(advanced()!.getAttribute('aria-expanded')).toBe('true');
        const html = document.body.innerHTML;
        const review = html.indexOf('sheet__review');
        const files = html.indexOf('sheet__files');
        const notice = html.indexOf('sheet__theme-effects');
        expect(review).toBeGreaterThan(-1);
        expect(files).toBeGreaterThan(review);
        expect(notice).toBeGreaterThan(files);
        expect(document.querySelectorAll('.sheet__file')).toHaveLength(2);
        expect(document.querySelector('.sheet__body')).toBeNull();
        advanced()!.click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(document.querySelector('.sheet__file')).toBeNull();
    });

    test('a non-theme item keeps the whole sheet', async () => {
        await open('skill');
        expect(advanced()).toBeNull();
        for (const kept of ['KEYID123', 'catalog.example', 'DIGESTDIGEST', '212,888', i18n.t('skill.sheet.scope.legend')]) {
            expect(text()).toContain(kept);
        }
        expect(document.querySelector('.sheet__body')).not.toBeNull();
        expect(document.querySelectorAll('.sheet__file')).toHaveLength(2);
    });
});
