/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import CatalogCard from './CatalogCard.svelte';
import { cardView } from './card';
import { previewPalette } from '../themes-page/preview-palette';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const KINDS = ['mod', 'skill', 'theme', 'plugin', 'loadout'] as const;

let handle: Record<string, unknown> | null = null;

function viewOf(kind: string, untrusted = false, extra: Record<string, unknown> = {}) {
    return cardView(
        {
            id: `a/${kind}-one`,
            name: `${kind}-one`,
            publisher: 'a',
            latest: '1.0.0',
            kind,
            card: { title: `The ${kind}`, brief: 'does a thing' },
            versions: [{ v: '1.0.0', digest: 'a'.repeat(64), review: { status: 'reviewed', verdict: 'clean', warnings: [] } }],
            ...extra,
        } as never,
        untrusted,
    );
}

function paint(card: ReturnType<typeof viewOf>, props: Record<string, unknown> = {}): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    handle = mount(CatalogCard, {
        target: host,
        props: {
            card,
            t,
            state: { kind: 'idle' },
            onInstall() {},
            onUpdate() {},
            onOpen() {},
            onAdd() {},
            ...props,
        } as never,
    });
    return host;
}

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

describe('the kind mark and band', () => {
    test.each(KINDS)('the %s card has one mark right before the title, data-kind and its band', (kind) => {
        const host = paint(viewOf(kind));
        const marks = host.querySelectorAll('.kind-mark');
        expect(marks).toHaveLength(1);
        expect(marks[0]?.classList.contains(`kind-mark--${kind}`)).toBe(true);
        expect(marks[0]?.nextElementSibling?.classList.contains('catalog-card__title')).toBe(true);
        const card = host.querySelector('.catalog-card') as HTMLElement;
        expect(card.getAttribute('data-kind')).toBe(kind);
        expect(card.classList.contains(`kind-band--${kind}`)).toBe(true);
        expect(host.querySelector('.catalog-card__foot')).toBeNull();
    });

    test.each(KINDS)('the %s list row has one mark right before the title', (kind) => {
        const host = paint(viewOf(kind), { list: true });
        const marks = host.querySelectorAll('.kind-mark');
        expect(marks).toHaveLength(1);
        expect(marks[0]?.classList.contains(`kind-mark--${kind}`)).toBe(true);
        expect(marks[0]?.nextElementSibling?.classList.contains('catalog-card__title')).toBe(true);
        expect(host.querySelector('.catalog-row')?.getAttribute('data-kind')).toBe(kind);
    });
});

describe('the picture ladder', () => {
    const palette = previewPalette({ id: 'x', cssVars: {}, xterm: {} } as never);

    test('a theme with a palette draws the miniature, without one the letter slab', () => {
        const withPalette = paint(viewOf('theme'), { palette });
        expect(withPalette.querySelector('[data-preview-size="card"]')).not.toBeNull();
        expect(withPalette.querySelector('.catalog-card__letter')).toBeNull();
        unmount(handle as Record<string, unknown>);
        document.body.innerHTML = '';
        const bare = paint(viewOf('theme'));
        expect(bare.querySelector('[data-preview-size]')).toBeNull();
        expect(bare.querySelector('.catalog-card__letter')?.textContent).toBe('T');
    });

    test('a skill with no media draws the letter slab and a mod draws the mod glyph', () => {
        const skill = paint(viewOf('skill'));
        expect(skill.querySelector('.catalog-card__letter')?.textContent).toBe('T');
        unmount(handle as Record<string, unknown>);
        document.body.innerHTML = '';
        const mod = paint(viewOf('mod'));
        expect(mod.querySelector('.catalog-card__letter')).toBeNull();
        expect(mod.querySelector('[data-card-media] svg')?.getAttribute('data-icon')).toBe('mod');
    });
});

describe('the verdict and the untrusted card', () => {
    test('the ONE card: no meta line, no source line, a three line brief and a 16:9 picture', () => {
        const host = paint(viewOf('skill'));
        expect(host.querySelector('.catalog-card__meta')).toBeNull();
        expect(host.querySelector('[data-catalog-credit]')).toBeNull();
        expect(host.querySelector('.verdict-mark')).toBeNull();
        expect(host.querySelector('.catalog-card__flags')).toBeNull();
        expect(host.querySelector('.catalog-card__brief')).not.toBeNull();
        const css = readFileSync(resolve(__dirname, 'warez-card.css'), 'utf8');
        expect(css).toMatch(/aspect-ratio: 16 \/ 9;/);
        expect(css).toMatch(/line-clamp: 3;[\s\S]*min-height: calc\(3 \* 1\.45em\)/);
    });

    test('an untrusted card says untrusted key with the crossed shape and a disabled add', () => {
        const host = paint(viewOf('skill', true));
        const mark = host.querySelector('.catalog-card__flags .verdict-mark');
        expect(mark?.getAttribute('data-verdict')).toBe('blocked');
        expect(mark?.textContent?.trim()).toBe('untrusted key');
        const add = host.querySelector('[data-act="add"]') as HTMLButtonElement;
        expect(add.disabled).toBe(true);
    });

    test('a trusted card has a live add', () => {
        const add = paint(viewOf('skill')).querySelector('[data-act="add"]') as HTMLButtonElement;
        expect(add.disabled).toBe(false);
    });
});
