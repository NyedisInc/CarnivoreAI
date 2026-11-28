/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';

vi.mock('./card-media', () => ({
    catalogMediaUrl: vi.fn(async (sha: string) => `blob:mock-${sha.slice(0, 8)}`),
}));

import ScreenshotGallery from './ScreenshotGallery.svelte';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    vi.clearAllMocks();
});

const settle = async () => {
    for (let i = 0; i < 10; i += 1) {
        await Promise.resolve();
        flushSync();
    }
};

describe('ScreenshotGallery (#3404)', () => {
    test('renders thumbnails, opens lightbox on click, and cycles with next/prev', async () => {
        mounted = mount(ScreenshotGallery, {
            target: document.body,
            props: {
                itemName: 'Pill Panic',
                screenshots: [
                    { sha: 'a'.repeat(64), w: 1280, h: 800, source: 'captured', caption: 'Terminal mode' },
                    { sha: 'b'.repeat(64), w: 1280, h: 800, source: 'author', caption: '3D mode' },
                ],
                t,
            },
        });
        await settle();

        const thumbs = document.querySelectorAll('[data-screenshot-thumb]');
        expect(thumbs).toHaveLength(2);
        expect(document.querySelector('[data-screenshot-gallery]')?.textContent).toContain('live preview');

        (thumbs[0] as HTMLButtonElement).click();
        await settle();

        const lightbox = document.querySelector('[data-screenshot-lightbox]');
        expect(lightbox).not.toBeNull();
        expect(lightbox?.textContent).toContain('1 / 2');

        (document.querySelector('[data-screenshot-next]') as HTMLButtonElement).click();
        await settle();
        expect(document.querySelector('[data-screenshot-lightbox]')?.textContent).toContain('2 / 2');
    });

    test('renders nothing when screenshots array is empty', async () => {
        mounted = mount(ScreenshotGallery, {
            target: document.body,
            props: { screenshots: [], t },
        });
        await settle();
        expect(document.querySelector('[data-screenshot-gallery]')).toBeNull();
    });
});
