/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

import CardImageRow from './CardImageRow.svelte';
import { clearPreview, previewFor } from './card-image-store.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from './catalog';
import type { CardView } from './card';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);

function png(w: number, h: number, size = 64): Uint8Array {
    const b = new Uint8Array(size);
    b.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]);
    const v = new DataView(b.buffer);
    v.setUint32(16, w);
    v.setUint32(20, h);
    return b;
}

function jpeg(w: number, h: number): Uint8Array {
    const b = new Uint8Array(32);
    b.set([0xff, 0xd8, 0xff, 0xc0, 0, 17, 8]);
    const v = new DataView(b.buffer);
    v.setUint16(7, h);
    v.setUint16(9, w);
    return b;
}

function webp(w: number, h: number): Uint8Array {
    const b = new Uint8Array(40);
    b.set([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50, 0x56, 0x50, 0x38, 0x58, 10, 0, 0, 0, 0, 0, 0, 0]);
    b.set([(w - 1) & 255, ((w - 1) >> 8) & 255, ((w - 1) >> 16) & 255, (h - 1) & 255, ((h - 1) >> 8) & 255, ((h - 1) >> 16) & 255], 24);
    return b;
}

const card = (over: Partial<CardView> = {}): CardView =>
    ({ kind: 'skill', indexKind: over.kind ?? 'skill', id: 'ada/tool', publisher: 'ada', mediaSha: null, ...over }) as CardView;

let sendHero: ReturnType<typeof vi.fn>;
let panel: Record<string, unknown> | null = null;

function host(account: () => Promise<unknown>): CatalogHost {
    return { publishAccount: account, sendHero } as unknown as CatalogHost;
}
const ok = (handle: string) => () => Promise.resolve({ handle });

async function paint(h: CatalogHost, c: CardView, signedIn = true): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(CardImageRow, { target, props: { card: c, host: h, signedIn, t } as never }) as never;
    await vi.waitFor(() => flushSync());
    await new Promise((r) => setTimeout(r, 0));
    flushSync();
}
const row = () => document.querySelector('[data-card-image]');
const note = () => document.querySelector('.card-image__note')?.textContent ?? '';
const buttons = () => [...document.querySelectorAll('button')].map((b) => b.textContent?.trim());

async function choose(bytes: Uint8Array, name = 'a.png', size?: number): Promise<void> {
    const file = new File([bytes as unknown as BlobPart], name);
    if (size !== undefined) Object.defineProperty(file, 'size', { value: size });
    const input = document.querySelector('input[type=file]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => {
        flushSync();
        expect(document.querySelector('.card-image__note')).not.toBeNull();
    });
}

beforeEach(() => {
    sendHero = vi.fn().mockResolvedValue({ submission_id: 'sub' });
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    clearPreview('ada/tool');
    clearPreview('ada/theme');
    document.body.innerHTML = '';
});

describe('who sees the row', () => {
    test('present for the matching handle on a skill and a theme; absent otherwise', async () => {
        await paint(host(ok('ADA')), card());
        expect(row()).not.toBeNull();
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(host(ok('ada')), card({ kind: 'theme', id: 'ada/theme' }));
        expect(row()).not.toBeNull();
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(host(ok('bob')), card());
        expect(row()).toBeNull();
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(host(() => Promise.reject(new Error('403'))), card());
        expect(row()).toBeNull();
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(host(ok('ada')), card(), false);
        expect(row()).toBeNull();
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(host(ok('ada')), card({ kind: 'mod' }));
        expect(row()).toBeNull();
    });
});

describe('the row draws only on the item the server will bind (#1555 hardening)', () => {
    async function paintLive(h: CatalogHost, c: CardView) {
        const live = new SvelteMap<string, boolean>([['in', true]]);
        const target = document.createElement('div');
        document.body.appendChild(target);
        const props = { card: c, host: h, t, get signedIn() { return live.get('in') ?? false; } };
        panel = mount(CardImageRow, { target, props: props as never }) as never;
        const settle = async () => {
            await new Promise((r) => setTimeout(r, 0));
            flushSync();
        };
        await settle();
        return {
            set: async (v: boolean) => {
                live.set('in', v);
                await settle();
            },
        };
    }

    test('a publisher field that matches while the id namespace does not draws no row', async () => {
        await paint(host(ok('ada')), card({ id: 'bob/tool', publisher: 'ada' }));
        expect(row()).toBeNull();
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(host(ok('ada')), card({ id: 'ADA/tool', publisher: 'ada' }));
        expect(row()).not.toBeNull();
    });

    test('signing out then in as another handle re-reads the account', async () => {
        const handles = ['ada', 'bob'];
        const read = vi.fn(() => Promise.resolve({ handle: handles.shift() }));
        const live = await paintLive(host(read), card());
        expect(row()).not.toBeNull();
        await live.set(false);
        expect(row()).toBeNull();
        await live.set(true);
        expect(read).toHaveBeenCalledTimes(2);
        expect(row()).toBeNull();
    });

    test('a failed account read is not kept: a remount on the same host with no sign-out reads again', async () => {
        const read = vi.fn().mockRejectedValueOnce(new Error('503')).mockResolvedValue({ handle: 'ada' });
        const h = host(read);
        await paint(h, card());
        expect(row()).toBeNull();
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(h, card());
        expect(read).toHaveBeenCalledTimes(2);
        expect(row()).not.toBeNull();
    });

    test('a failed account read is not kept: the next sign-in reads again and the row appears', async () => {
        const read = vi.fn().mockRejectedValueOnce(new Error('503')).mockResolvedValue({ handle: 'ada' });
        const live = await paintLive(host(read), card());
        expect(row()).toBeNull();
        await live.set(false);
        await live.set(true);
        expect(read).toHaveBeenCalledTimes(2);
        expect(row()).not.toBeNull();
    });
});

describe('what it refuses and what it sends', () => {
    const cases: [string, Uint8Array, string, Record<string, unknown>, number?][] = [
        ['not an image', new Uint8Array(10), 'skill.publish.refused.bad_image', {}],
        ['over 512 KiB', png(1536, 1024), 'skill.publish.hero.too_big', {}, 513 * 1024],
        ['too small', png(1000, 400), 'skill.publish.card_image.too_small', { w: '1000', h: '400' }],
        ['wrong shape', jpeg(1200, 1200), 'skill.publish.card_image.bad_shape', { ratio: '1.0' }],
        ['too wide a side', webp(9000, 1000), 'skill.publish.card_image.too_many_px', { w: '9000', h: '1000' }],
    ];
    test.each(cases)('%s names its reason and sends nothing', async (_n, bytes, key, params, size) => {
        await paint(host(ok('ada')), card());
        await choose(bytes, 'f', size);
        expect(note()).toBe(t(key, params));
        expect(document.querySelector('.card-image__note--bad')).not.toBeNull();
        expect(sendHero).not.toHaveBeenCalled();
        expect(previewFor('ada/tool')).toBeNull();
    });

    test('a valid file previews locally, sends once on request, and a refusal keeps the preview', async () => {
        await paint(host(ok('ada')), card({ kind: 'theme', id: 'ada/theme' }));
        await choose(png(1536, 1024));
        expect(previewFor('ada/theme')?.w).toBe(1536);
        expect(note()).toBe(t('skill.publish.card_image.local_only'));
        expect(sendHero).not.toHaveBeenCalled();

        sendHero.mockRejectedValueOnce({ detail: { code: 'image_size', detail: 'the image is 1000x400' } });
        (([...document.querySelectorAll('button')].find((b) => b.textContent?.includes('send for review'))) as HTMLButtonElement).click();
        await vi.waitFor(() => {
            flushSync();
            expect(document.querySelector('.card-image__note--bad')).not.toBeNull();
        });
        expect(previewFor('ada/theme')).not.toBeNull();

        (([...document.querySelectorAll('button')].find((b) => b.textContent?.includes('send for review'))) as HTMLButtonElement).click();
        await vi.waitFor(() => {
            flushSync();
            expect(note()).toBe(t('skill.publish.hero.sent'));
        });
        expect(sendHero).toHaveBeenCalledTimes(2);
        expect(sendHero.mock.calls[1]![0]).toMatchObject({ kind: 'theme', name: 'theme' });
        expect(typeof sendHero.mock.calls[1]![0].image_base64).toBe('string');
        expect(note()).toBe(t('skill.publish.hero.sent'));
        expect(buttons()).toContain('clear preview');
        expect(buttons()).not.toContain('send for review');
    });
});
