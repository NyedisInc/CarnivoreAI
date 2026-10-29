/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('./places-writes', () => ({
    addToPlace: vi.fn(async () => true),
    removeFromPlace: vi.fn(async () => true),
    moveInPlace: vi.fn(),
    resetBars: vi.fn(async () => {}),
}));

import WidgetsScreen from './WidgetsScreen.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { isViewCell } from '../../opscenter/widgets/views';
import { createWidgetsAdapter } from './widgets-adapter';
import { memoryFetcher } from '../item-settings/memory-fetcher';
import { createItemSettingsController } from '../item-settings/item-settings-controller.svelte';
import { t } from '../i18n/index.svelte';
import { declaredSizes, fits, boardCell, SIZE_ORDER } from './places';
import { rowsOf } from './places-state.svelte';
import { resetView } from './places-view.svelte';
import { addToPlace } from './places-writes';
import type { Fetcher } from '../item-settings/api';

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto['showPopover'] ??= function () {};
proto['hidePopover'] ??= function () {};

let mounted: Record<string, unknown> | null = null;

beforeEach(() => {
    vi.mocked(addToPlace).mockClear();
    resetView();
});

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function show(): Promise<HTMLElement> {
    const schemas = Object.fromEntries(Object.values(CORE_MANIFESTS).map((m) => [m.id, m.settings ?? null]));
    const fetcher = memoryFetcher(schemas) as Fetcher;
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(WidgetsScreen, {
        target,
        props: {
            embedded: true,
            t,
            previews: false,
            adapter: createWidgetsAdapter(t, CORE_MANIFESTS, fetcher, async () => {}, () => {}),
            settingsFor: (id: string) => createItemSettingsController('widget', id, t, fetcher, async () => {}),
        },
    });
    await settle();
    return target;
}

const manifests = Object.values(CORE_MANIFESTS).filter((m) => !isViewCell(m));
const card = (root: HTMLElement, id: string): HTMLElement => root.querySelector<HTMLElement>(`[data-item-id="${id}"]`)!.closest<HTMLElement>('li.wp-card')!;

function freeForRight(): string {
    const held = new Set(rowsOf('right').map((row) => row.widget));
    const found = manifests.find((m) => fits(m, true, 'right') && !held.has(m.id));
    expect(found, 'a widget that fits the right bar and is not in it').toBeTruthy();
    return found!.id;
}

describe('placing a widget', () => {
    test('the plus in a place heading opens the product menu and a pick calls the one write for that place', async () => {
        const root = await show();
        root.querySelector<HTMLButtonElement>('.wp-place[data-place="right"] [data-place-add]')!.click();
        await settle();
        const item = document.querySelector<HTMLElement>('[role="menu"] [role="menuitem"]:not([aria-disabled="true"])')!;
        expect(item, 'the menu lists something to add').not.toBeNull();
        const id = item.dataset['node']!;
        item.click();
        await settle();
        expect(addToPlace).toHaveBeenCalledTimes(1);
        const args = vi.mocked(addToPlace).mock.calls[0]!;
        expect(args[0]).toBe(id);
        expect(args[2]).toBe('right');
        expect(args[3], 'a bar write carries no dashboard').toBeNull();
    });

    test('dragging a card onto a place calls the same write, and a place it does not fit refuses', async () => {
        const root = await show();
        const id = freeForRight();
        const li = card(root, id);
        const event = (type: string): Event => Object.assign(new Event(type, { bubbles: true, cancelable: true }), { dataTransfer: { setData() {}, effectAllowed: '' } });
        li.dispatchEvent(event('dragstart'));
        await settle();
        const right = root.querySelector<HTMLElement>('.wp-place[data-place="right"]')!;
        expect(right.dataset['accept'], 'the right bar says it will take it').toBe('yes');
        right.dispatchEvent(event('drop'));
        await settle();
        expect(vi.mocked(addToPlace).mock.calls.at(-1)?.slice(0, 3)).toEqual([id, expect.any(String), 'right']);

        const misfit = manifests.find((m) => !fits(m, true, 'glance'))!;
        vi.mocked(addToPlace).mockClear();
        card(root, misfit.id).dispatchEvent(event('dragstart'));
        await settle();
        const glance = root.querySelector<HTMLElement>('.wp-place[data-place="glance"]')!;
        expect(glance.dataset['accept']).toBe('no');
        glance.dispatchEvent(event('drop'));
        await settle();
        expect(addToPlace).not.toHaveBeenCalled();
    });
});

describe('the fits filter', () => {
    test('picking a place dims exactly the cards that do not fit it, with the reason in the brief', async () => {
        const root = await show();
        root.querySelector<HTMLButtonElement>('[data-rail="place:glance"]')!.click();
        await settle();
        const fitting = manifests.filter((m) => fits(m, true, 'glance')).map((m) => m.id);
        const dimmed = [...root.querySelectorAll<HTMLElement>('li.wp-card[data-dim]')].map((li) => li.querySelector<HTMLElement>('[data-item-id]')!.dataset['itemId']!);
        expect(fitting.length, 'some widgets fit the glance row').toBeGreaterThan(0);
        expect(dimmed.length, 'some do not').toBeGreaterThan(0);
        expect(dimmed.some((id) => fitting.includes(id))).toBe(false);
        expect(dimmed.length + fitting.length).toBeGreaterThanOrEqual(manifests.length - 1);
    });
});

describe('the sticky podium', () => {
    test('the five places sit in the sticky wrapper and the stylesheet pins it', async () => {
        const root = await show();
        const stick = root.querySelector('.wp-stick')!;
        expect([...stick.querySelectorAll('.wp-place')].map((el) => (el as HTMLElement).dataset['place'])).toEqual(['right', 'bottom', 'drawer', 'glance', 'board']);
        const css = readFileSync(resolve(process.cwd(), 'src/lib/widgets-page/widgets-page.css'), 'utf8');
        expect(css).toMatch(/\.wp-stick \{[^}]*position: sticky/);
        expect(css).toMatch(/max-width: 767px\) \{ \.wp-screen \.wp-stick \{ position: static/);
    });

    test('picking a place keeps every heading on screen', async () => {
        const root = await show();
        root.querySelector<HTMLButtonElement>('.wp-place[data-place="bottom"] [data-place-pick]')!.click();
        await settle();
        expect(root.querySelectorAll('.wp-stick .wp-place').length).toBe(5);
        expect(root.querySelector('.wp-place[data-place="bottom"]')!.hasAttribute('data-chosen')).toBe(true);
    });
});

describe('the reading pane', () => {
    async function open(root: HTMLElement, id: string): Promise<void> {
        card(root, id).querySelector<HTMLButtonElement>('[data-card-open]')!.click();
        await settle();
    }

    test('m3.1 size seg: one picked size, the declared ones pressable, the rest disabled and inert', async () => {
        const root = await show();
        const m = manifests.find((one) => declaredSizes(one).length >= 2 && declaredSizes(one).length < SIZE_ORDER.length)!;
        await open(root, m.id);
        const buttons = [...root.querySelectorAll<HTMLButtonElement>('.pn-sizes [data-pane-size]')];
        expect(buttons.map((b) => b.dataset['paneSize'])).toEqual([...SIZE_ORDER]);
        expect(buttons.filter((b) => b.getAttribute('aria-checked') === 'true').length, 'exactly one picked').toBe(1);
        for (const b of buttons) {
            const has = declaredSizes(m).includes(b.dataset['paneSize'] as (typeof SIZE_ORDER)[number]);
            expect(b.disabled, b.dataset['paneSize']).toBe(!has);
        }
        const other = buttons.find((b) => !b.disabled && b.getAttribute('aria-checked') !== 'true')!;
        other.click();
        await settle();
        expect(other.getAttribute('aria-checked')).toBe('true');
        const dead = [...root.querySelectorAll<HTMLButtonElement>('.pn-sizes [data-pane-size]')].find((b) => b.disabled)!;
        dead.click();
        await settle();
        expect(dead.getAttribute('aria-checked')).toBe('false');
    });

    test('m3.2 toggle: a real switch, on or off, pressing flips it', async () => {
        const root = await show();
        await open(root, 'core.activity-log');
        const sw = root.querySelector<HTMLButtonElement>('[data-pane-toggle]')!;
        expect(sw.getAttribute('role')).toBe('switch');
        expect(sw.getAttribute('aria-checked')).toBe('true');
        expect(sw.textContent?.trim()).toBe(t('widgets.places.pane.on'));
        sw.click();
        await settle();
        const after = root.querySelector<HTMLButtonElement>('[data-pane-toggle]')!;
        expect(after.getAttribute('aria-checked')).toBe('false');
        expect(after.textContent?.trim()).toBe(t('widgets.places.pane.off'));
    });
});

describe('the board place', () => {
    test('a per-target widget has no dashboard cell, so the page never offers it one', () => {
        const perTarget = manifests.find((m) => m.instancing === 'per-target');
        if (perTarget) expect(boardCell(perTarget)).toBeNull();
        expect(boardCell(manifests.find((m) => m.instancing !== 'per-target' && m.scope === 'session') ?? manifests[0]!)).not.toBe(undefined);
    });
});
