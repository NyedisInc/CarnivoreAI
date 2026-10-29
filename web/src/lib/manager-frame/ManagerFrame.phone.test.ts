/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ManagerFrame from './ManagerFrame.svelte';
import { viewport } from '../../opscenter/engine/viewport.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    viewport.narrow = false;
    document.body.innerHTML = '';
});

async function frame(narrow: boolean, extra: Record<string, unknown> = {}): Promise<HTMLElement> {
    viewport.narrow = narrow;
    Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true });
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(ManagerFrame, {
        target,
        props: {
            title: 'things',
            items: [],
            status: { kind: 'ready' },
            query: '',
            onQuery: () => {},
            filters: [{ id: 'on', label: 'on', on: false, test: () => true }],
            viewKey: 'phone-test',
            onClose: () => {},
            t,
            ...extra,
        },
    });
    await tick();
    flushSync();
    return target;
}

describe('search placement on a phone', () => {
    test('narrow: ONE bar holds back, the search frame, the fitting filters and the view flip', async () => {
        const root = await frame(true);
        expect(root.querySelectorAll('input[type=search]').length).toBe(1);
        expect(root.querySelector('.oc-titlebar .oc-titlebar__omni .oc-titlebar__title')).not.toBeNull();
        expect(root.querySelector('.oc-titlebar__omni input[type=search]')).not.toBeNull();
        expect(root.querySelector('[data-page-close]')).toBeNull();
        expect(root.querySelector('.oc-titlebar [data-page-back]')).not.toBeNull();
        expect(root.querySelector('.oc-titlebar__controls .oc-page__chips')).not.toBeNull();
        expect(root.querySelector('.oc-titlebar__controls [data-view-flip]')).not.toBeNull();
        expect(root.querySelector('.oc-page__view')).toBeNull();
        expect(root.querySelector('.oc-page__bar')).toBeNull();
    });

    test('narrow: the flip names the switch and swaps the view', async () => {
        const root = await frame(true);
        const flip = root.querySelector<HTMLButtonElement>('[data-view-flip]')!;
        expect(flip.getAttribute('aria-label')).toBe('grid view, switch to list');
        flip.click();
        await tick();
        flushSync();
        expect(root.querySelector<HTMLButtonElement>('[data-view-flip]')!.getAttribute('aria-label')).toBe('list view, switch to grid');
    });

    test('narrow: filters that would squeeze the search frame take one row under the bar', async () => {
        const wide = ['installed', 'available', 'updates'].map((id) => ({ id, label: id, on: false, test: () => true }));
        const root = await frame(true, { filters: wide });
        expect(root.querySelector('.oc-titlebar__controls .oc-page__chips')).toBeNull();
        expect(root.querySelector('.oc-page__bar .oc-page__chips')).not.toBeNull();
        expect(root.querySelector('.oc-titlebar__controls [data-view-flip]')).not.toBeNull();
    });

    test('narrow with nothing but a search: no toolbar row at all', async () => {
        const root = await frame(true, { filters: [], viewKey: undefined });
        expect(root.querySelector('.oc-titlebar__omni input[type=search]')).not.toBeNull();
        expect(root.querySelector('.oc-page__bar')).toBeNull();
    });

    test('wide: the search is in the bar and the title bar has no close button', async () => {
        const root = await frame(false);
        expect(root.querySelector('.oc-page__bar input[type=search]')).not.toBeNull();
        expect(root.querySelector('.oc-titlebar input[type=search]')).toBeNull();
        expect(root.querySelector('[data-page-close]')).toBeNull();
        expect(root.querySelector('[data-page-back]')).toBeNull();
        expect(root.querySelector('[data-view-flip]')).toBeNull();
    });

    test('embedded keeps its own toolbar even on a phone', async () => {
        const root = await frame(true, { embedded: true });
        expect(root.querySelector('.oc-page__bar input[type=search]')).not.toBeNull();
        expect(root.querySelectorAll('input[type=search]').length).toBe(1);
    });
});
