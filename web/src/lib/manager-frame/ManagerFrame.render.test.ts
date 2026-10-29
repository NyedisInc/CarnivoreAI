/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ManagerFrameDemo from '../../style-guide/specimens/ManagerFrameDemo.svelte';
import ManagerFrame from './ManagerFrame.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { PSEUDO_LOCALE } from '../../../../client/js/i18n/pseudo.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const pseudo = createI18n({ locale: PSEUDO_LOCALE }) as { t: Translate };
const tPseudo: Translate = (key, params) => pseudo.t(key, params);

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function show(props: Record<string, unknown> = {}): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(ManagerFrameDemo, { target, props: { t, ...props } });
    await Promise.resolve();
    await tick();
    flushSync();
    return target;
}

async function settle(): Promise<void> {
    await Promise.resolve();
    await Promise.resolve();
    await tick();
    flushSync();
}

const text = (root: HTMLElement, selector: string): string =>
    root.querySelector(selector)?.textContent?.trim() ?? '';

describe('states', () => {
    test('loading prints the word in place, and no list or count', async () => {
        const root = await show({ part: 'loading' });
        expect(text(root, '.oc-page__state')).toBe('reading');
        expect(root.querySelector('.oc-page__items')).toBeNull();
        expect(root.querySelector('.oc-titlebar__count')).toBeNull();
    });

    test('error prints the title, the sentence and a retry', async () => {
        const root = await show({ part: 'error' });
        expect(text(root, '.oc-page__error-title')).toBe('could not read the list');
        expect(text(root, '.oc-page__error-detail')).toContain('503');
        expect(root.querySelector('.oc-page__error button')?.textContent?.trim()).toBe('try again');
    });

    test('an empty list and no matches are different sentences', async () => {
        const empty = await show({ part: 'empty' });
        expect(text(empty, '.oc-page__empty-text')).toBe('nothing here yet');
        expect(empty.querySelector('.oc-page__empty button')).toBeNull();
        unmount(mounted!);
        mounted = null;

        const root = await show();
        const input = root.querySelector<HTMLInputElement>('.oc-field')!;
        input.value = 'nothing matches this';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        expect(text(root, '.oc-page__empty-text')).toBe('no matches for this search and these filters');
        expect(text(root, '.oc-titlebar__count')).toBe('0 of 4');
        root.querySelector<HTMLButtonElement>('.oc-page__empty button')!.click();
        flushSync();
        expect(root.querySelectorAll('.mgr-card')).toHaveLength(4);
        expect(input.value).toBe('');
    });
});

describe('the list', () => {
    test('counts the items and presses a chip into a filter', async () => {
        const root = await show();
        expect(text(root, '.oc-titlebar__count')).toBe('4 items');
        const chip = root.querySelector<HTMLButtonElement>('.oc-chip')!;
        expect(chip.getAttribute('aria-pressed')).toBe('false');
        chip.click();
        flushSync();
        expect(chip.getAttribute('aria-pressed')).toBe('true');
        expect(root.querySelectorAll('.mgr-card')).toHaveLength(2);
        expect(text(root, '.oc-titlebar__count')).toBe('2 of 4');
    });

    test('a switch only where the state is measured, saying it in words', async () => {
        const root = await show();
        const switches = root.querySelectorAll<HTMLButtonElement>('[role="switch"]');
        expect(switches).toHaveLength(3);
        expect(root.querySelector('[data-item-id="notes-export"] [role="switch"]')).toBeNull();
        const on = root.querySelector<HTMLButtonElement>('[data-item-id="mark-unread"] [role="switch"]')!;
        expect(on.getAttribute('aria-checked')).toBe('true');
        expect(on.textContent?.trim()).toBe('on');
        expect(on.getAttribute('aria-label')).toBe('turn mark unread on or off');
    });

    test('a switch shows what the route answered', async () => {
        const root = await show();
        const off = root.querySelector<HTMLButtonElement>('[data-item-id="open-as-component"] [role="switch"]')!;
        off.click();
        flushSync();
        expect(off.disabled).toBe(true);
        expect(off.textContent?.trim()).toBe('working');
        await settle();
        const after = root.querySelector<HTMLButtonElement>('[data-item-id="open-as-component"] [role="switch"]')!;
        expect(after.getAttribute('aria-checked')).toBe('true');
        expect(after.disabled).toBe(false);
    });

    test('a refused switch keeps its state and says why beside it', async () => {
        const root = await show({ refuseToggle: true });
        root.querySelector<HTMLButtonElement>('[data-item-id="mark-unread"] [role="switch"]')!.click();
        await settle();
        const card = root.querySelector('[data-item-id="mark-unread"]')!;
        expect(card.querySelector('[role="switch"]')!.getAttribute('aria-checked')).toBe('true');
        expect(card.querySelector('.mgr-card__error')?.textContent).toContain('required by an open layout');
    });
});

describe('the detail pane and the keyboard', () => {
    test('the name opens the pane and takes focus; Escape closes it back onto the name', async () => {
        const root = await show();
        const opener = root.querySelector<HTMLButtonElement>('[data-item-id="share-read-only"] .mgr-card__open')!;
        opener.click();
        await settle();
        const pane = root.querySelector('.oc-page__detail')!;
        expect(pane).not.toBeNull();
        expect(text(root, '.mgr__detail-title')).toBe('share read only');
        expect(document.activeElement).toBe(root.querySelector('.mgr__detail-title'));
        expect(opener.getAttribute('aria-expanded')).toBe('true');

        root.querySelector('.mgr')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await settle();
        expect(root.querySelector('.oc-page__detail')).toBeNull();
        expect(document.activeElement).toBe(
            root.querySelector('[data-item-id="share-read-only"] .mgr-card__open'),
        );
    });

    test('with no detail snippet the name is text, not a control', async () => {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(ManagerFrame, {
            target,
            props: {
                title: 'wrappers',
                items: [{ id: 'keyc', name: 'keyc' }],
                status: { kind: 'ready' },
                query: '',
                onQuery: () => {},
                t,
                embedded: true,
            },
        });
        flushSync();
        expect(target.querySelector('.mgr-card__open')).toBeNull();
        expect(text(target, '.mgr-card__name')).toBe('keyc');
        expect(target.querySelector('[role="switch"]')).toBeNull();
        expect(target.querySelector('[data-page-close]')).toBeNull();
    });

    test('an overlay page draws no close button and Escape never closes it', async () => {
        let closed = 0;
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(ManagerFrame, {
            target,
            props: {
                title: 'wrappers',
                items: [],
                status: { kind: 'ready' },
                query: '',
                onQuery: () => {},
                onClose: () => (closed += 1),
                t,
            },
        });
        flushSync();
        expect(target.querySelector('[data-page-close]')).toBeNull();
        target.querySelector('.mgr')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        expect(closed).toBe(0);
    });
});

describe('install, export, remove and limits (issue #888)', () => {
    test('a page with no share handlers draws no action row and no notes', async () => {
        const root = await show();
        (root.querySelector('.mgr-card__open') as HTMLButtonElement).click();
        await settle();
        expect(root.querySelector('[data-mgr-actions]')).toBeNull();
        expect(root.querySelector('[data-mgr-limits]')).toBeNull();
        expect(text(root, '[data-mgr-install]')).toBe('install');
    });

    test('export names the file it saved', async () => {
        const root = await show({ share: true });
        (root.querySelector('[data-mgr-export]') as HTMLButtonElement).click();
        await settle();
        expect(text(root, '[data-mgr-notice]')).toBe('saved share-read-only.plugin.json');
    });

    test('remove asks, then removes and says so; keep it does nothing', async () => {
        const root = await show({ share: true });
        (root.querySelector('[data-mgr-remove]') as HTMLButtonElement).click();
        await settle();
        expect(text(root, '[data-mgr-question]')).toBe('remove share read only? this cannot be undone.');
        (root.querySelector('[data-mgr-remove-cancel]') as HTMLButtonElement).click();
        await settle();
        expect(root.querySelectorAll('.mgr-card').length).toBe(4);
        (root.querySelector('[data-mgr-remove]') as HTMLButtonElement).click();
        await settle();
        (root.querySelector('[data-mgr-remove-confirm]') as HTMLButtonElement).click();
        await settle();
        await settle();
        expect(root.querySelectorAll('.mgr-card').length).toBe(3);
        expect(text(root, '[data-mgr-removed]')).toBe('removed share read only');
        expect(root.querySelector('.oc-page__detail')).toBeNull();
    });

    test('a blocked item draws remove disabled with the reason under it', async () => {
        const root = await show({ share: true });
        (root.querySelector('[data-item-id="mark-unread"] .mgr-card__open') as HTMLButtonElement).click();
        await settle();
        expect((root.querySelector('[data-mgr-remove]') as HTMLButtonElement).disabled).toBe(true);
        expect(text(root, '[data-mgr-remove-blocked]')).toBe('a builtin plugin cannot be removed');
    });

    test('limits are said on the page, under their label', async () => {
        const root = await show({ limits: true });
        expect(text(root, '[data-mgr-limits] .oc-label')).toBe('not on this page');
        expect(text(root, '.oc-page__limits .oc-notice')).toContain('none can be installed or removed here');
    });
});

describe('every word the frame owns comes from the catalog', () => {
    test('the pseudo-locale brackets the frame chrome', async () => {
        const root = await show({ t: tPseudo });
        const bracketed = (s: string) => s.startsWith('⟦') && s.endsWith('⟧');
        const owned = [
            root.querySelector('.oc-page__search .oc-field')!.getAttribute('aria-label') ?? '',
            root.querySelector<HTMLInputElement>('.oc-field')!.placeholder,
            text(root, '.oc-titlebar__count'),
            text(root, '[data-item-id="mark-unread"] .oc-check__label'),
            root.querySelector('[role="switch"]')!.getAttribute('aria-label') ?? '',
            root.querySelector('.oc-page__chips')!.getAttribute('aria-label') ?? '',
        ];
        expect(owned.filter((s) => !bracketed(s))).toEqual([]);
    });

    test('the pseudo-locale brackets the share actions and limits (issue #888)', async () => {
        const root = await show({ t: tPseudo, share: true, limits: true });
        const bracketed = (s: string) => s.startsWith('⟦') && s.endsWith('⟧');
        const before = [
            text(root, '[data-mgr-install]'),
            text(root, '[data-mgr-export]'),
            text(root, '[data-mgr-remove]'),
            text(root, '[data-mgr-limits] .oc-label'),
            root.querySelector('[data-mgr-actions]')!.getAttribute('aria-label') ?? '',
        ];
        (root.querySelector('[data-mgr-remove]') as HTMLButtonElement).click();
        await settle();
        const asking = [
            text(root, '[data-mgr-question]'),
            text(root, '[data-mgr-remove-confirm]'),
            text(root, '[data-mgr-remove-cancel]'),
        ];
        expect([...before, ...asking].filter((s) => !bracketed(s))).toEqual([]);
    });
});
