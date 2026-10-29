/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const { calls, answers, FakeApiError } = vi.hoisted(() => {
    class FakeApiError extends Error {
        readonly status: number;
        readonly code: string | null;
        readonly payload: unknown;
        constructor(message: string, status: number, code: string | null, payload: unknown) {
            super(message);
            this.name = 'ApiError';
            this.status = status;
            this.code = code;
            this.payload = payload;
        }
    }
    return {
        calls: [] as Array<{ path: string; body: unknown }>,
        answers: [] as unknown[],
        FakeApiError,
    };
});

vi.mock('../../opscenter/api/auth.svelte', () => ({
    ApiError: FakeApiError,
    authFetch: (path: string, init: RequestInit = {}) => {
        calls.push({ path, body: typeof init.body === 'string' ? JSON.parse(init.body) : null });
        const answer = answers.shift();
        if (answer instanceof Error) return Promise.reject(answer);
        return Promise.resolve(answer ?? {});
    },
}));

import FavoriteChips from './FavoriteChips.svelte';
import { setFavoritesPayload } from './favorites-store.svelte';
import { i18n, setLocale } from '../i18n/index.svelte';

setLocale('en');
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

function body(commands: string[], colors: Record<string, string> = {}, defaulted = false) {
    return {
        commands,
        command_details: commands.map((command) => ({
            command,
            description: `${command.slice(1)} it`,
            color: colors[command] ?? null,
        })),
        defaulted,
    };
}

let panel: Record<string, unknown> | null = null;
let selected: string[] = [];
let changes: unknown[] = [];

function paint(seed: ReturnType<typeof body>): HTMLElement {
    setFavoritesPayload(seed);
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(FavoriteChips, {
        target,
        props: {
            onSelect: (command: string) => selected.push(command),
            onChange: (payload: unknown) => changes.push(payload),
            describe: () => '',
        },
    }) as Record<string, unknown>;
    flushSync();
    return target;
}

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i++) {
        await new Promise((resolve) => setTimeout(resolve, 0));
        await tick();
    }
    flushSync();
}

function order(root: HTMLElement): string[] {
    return [...root.querySelectorAll<HTMLElement>('.command-chip .command-button')].map(
        (b) => b.dataset.command ?? '',
    );
}

function chip(root: HTMLElement, command: string): HTMLElement {
    const el = root.querySelector<HTMLElement>(`.command-chip[data-command="${command}"]`);
    if (!el) throw new Error(`no chip for ${command}`);
    return el;
}

function arrange(root: HTMLElement): void {
    root.querySelector<HTMLButtonElement>('[data-fav-arrange]')?.click();
    flushSync();
}

beforeEach(() => {
    calls.length = 0;
    answers.length = 0;
    selected = [];
    changes = [];
});

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('the row', () => {
    test('a tap on a chip inserts its command when not arranging', () => {
        const root = paint(body(['/clear', '/diff']));
        chip(root, '/diff').querySelector<HTMLButtonElement>('.command-button')?.click();
        expect(selected).toEqual(['/diff']);
        expect(calls).toEqual([]);
    });

    test('a coloured favorite carries its mark from the palette token', () => {
        const root = paint(body(['/clear', '/diff'], { '/diff': 'green' }));
        expect(chip(root, '/diff').dataset.favColor).toBe('green');
        expect(chip(root, '/diff').style.getPropertyValue('--fav-mark')).toBe('var(--oc-green)');
        expect(chip(root, '/clear').dataset.favColor).toBe('');
    });

    test('the empty and defaulted rows say what they are, from the catalog', () => {
        let root = paint(body([]));
        expect(root.textContent).toContain(t('slash.favorites.empty'));
        unmount(panel as never);
        panel = null;
        root = paint(body(['/clear'], {}, true));
        expect(root.textContent).toContain(t('slash.favorites.defaulted'));
    });
});

describe('a colour per favorite', () => {
    test('picking a swatch persists it and repaints from the answer', async () => {
        const root = paint(body(['/clear', '/diff']));
        arrange(root);
        chip(root, '/diff').querySelector<HTMLButtonElement>('.command-button')?.click();
        flushSync();
        expect(selected).toEqual([]);
        answers.push(body(['/clear', '/diff'], { '/diff': 'cyan' }));
        root.querySelector<HTMLButtonElement>('.fav-swatch[data-color="cyan"]')?.click();
        await settle();
        expect(calls).toEqual([
            { path: '/config/common-commands/color', body: { command: '/diff', color: 'cyan' } },
        ]);
        expect(chip(root, '/diff').dataset.favColor).toBe('cyan');
        const pressed = root.querySelector('.fav-swatch[aria-pressed="true"]') as HTMLElement;
        expect(pressed.dataset.color).toBe('cyan');
        expect(changes).toHaveLength(1);
    });

    test('the none swatch sends null', async () => {
        const root = paint(body(['/clear'], { '/clear': 'violet' }));
        arrange(root);
        chip(root, '/clear').querySelector<HTMLButtonElement>('.command-button')?.click();
        flushSync();
        answers.push(body(['/clear']));
        root.querySelector<HTMLButtonElement>('.fav-swatch[data-color=""]')?.click();
        await settle();
        expect(calls[0]?.body).toEqual({ command: '/clear', color: null });
        expect(chip(root, '/clear').dataset.favColor).toBe('');
    });

    test('every swatch is a labelled button, reachable by the keyboard', () => {
        const root = paint(body(['/clear']));
        arrange(root);
        chip(root, '/clear').querySelector<HTMLButtonElement>('.command-button')?.click();
        flushSync();
        const swatches = [...root.querySelectorAll<HTMLButtonElement>('.fav-swatch')];
        expect(swatches).toHaveLength(6);
        for (const s of swatches) {
            expect(s.tagName).toBe('BUTTON');
            expect(s.getAttribute('aria-label')).toBeTruthy();
            expect(s.hasAttribute('aria-pressed')).toBe(true);
        }
    });

    test('a stale colour write repaints the current row and says so', async () => {
        const root = paint(body(['/clear', '/diff']));
        arrange(root);
        chip(root, '/diff').querySelector<HTMLButtonElement>('.command-button')?.click();
        flushSync();
        answers.push(
            new FakeApiError('stale', 409, null, {
                detail: { code: 'favorites_stale', message: 'x', current: body(['/clear']) },
            }),
        );
        root.querySelector<HTMLButtonElement>('.fav-swatch[data-color="green"]')?.click();
        await settle();
        expect(order(root)).toEqual(['/clear']);
        expect(root.textContent).toContain(t('slash.favorites.stale'));
    });
});

describe('reordering', () => {
    test('alt+arrow moves the focused favorite, persists, and keeps focus on it', async () => {
        const root = paint(body(['/a', '/b', '/c']));
        const button = chip(root, '/a').querySelector<HTMLButtonElement>('.command-button')!;
        button.focus();
        answers.push(body(['/b', '/a', '/c']));
        button.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', altKey: true, bubbles: true }));
        await settle();
        expect(calls).toEqual([
            { path: '/config/common-commands/order', body: { commands: ['/b', '/a', '/c'] } },
        ]);
        expect(order(root)).toEqual(['/b', '/a', '/c']);
        expect((document.activeElement as HTMLElement | null)?.dataset.command).toBe('/a');
    });

    test('a bare arrow is not a move', async () => {
        const root = paint(body(['/a', '/b']));
        const button = chip(root, '/a').querySelector<HTMLButtonElement>('.command-button')!;
        button.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
        await settle();
        expect(calls).toEqual([]);
    });

    test('dragging a chip by its grip onto another persists the new order', async () => {
        const root = paint(body(['/a', '/b', '/c']));
        arrange(root);
        vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
            const chips = [...(this.parentElement?.children ?? [])];
            const i = chips.indexOf(this);
            return { left: i * 100, right: i * 100 + 90, top: 0, bottom: 50, width: 90, height: 50, x: i * 100, y: 0, toJSON: () => ({}) } as DOMRect;
        });
        const grip = chip(root, '/a').querySelector<HTMLElement>('[data-fav-grip]')!;
        grip.dispatchEvent(new MouseEvent('pointerdown', { clientX: 10, clientY: 10, bubbles: true }));
        grip.dispatchEvent(new MouseEvent('pointermove', { clientX: 250, clientY: 10, bubbles: true }));
        flushSync();
        expect(order(root)).toEqual(['/b', '/c', '/a']);
        answers.push(body(['/b', '/c', '/a']));
        grip.dispatchEvent(new MouseEvent('pointerup', { clientX: 250, clientY: 10, bubbles: true }));
        await settle();
        expect(calls).toEqual([
            { path: '/config/common-commands/order', body: { commands: ['/b', '/c', '/a'] } },
        ]);
        expect(order(root)).toEqual(['/b', '/c', '/a']);
        expect(changes).toHaveLength(1);
    });

    test('a failed reorder puts the row back and says why', async () => {
        const root = paint(body(['/a', '/b']));
        const button = chip(root, '/a').querySelector<HTMLButtonElement>('.command-button')!;
        answers.push(new FakeApiError('disk full', 500, null, null));
        button.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', altKey: true, bubbles: true }));
        await settle();
        expect(order(root)).toEqual(['/a', '/b']);
        expect(root.textContent).toContain(t('slash.favorites.failed', { reason: 'disk full' }));
    });

    test('a drag that ends where it started sends nothing', async () => {
        const root = paint(body(['/a', '/b']));
        arrange(root);
        const grip = chip(root, '/a').querySelector<HTMLElement>('[data-fav-grip]')!;
        grip.dispatchEvent(new MouseEvent('pointerdown', { clientX: 10, clientY: 10, bubbles: true }));
        grip.dispatchEvent(new MouseEvent('pointerup', { clientX: 10, clientY: 10, bubbles: true }));
        await settle();
        expect(calls).toEqual([]);
    });
});

describe('the chip star', () => {
    test('unstars through the explicit-state route', async () => {
        const root = paint(body(['/a', '/b']));
        answers.push(body(['/b']));
        chip(root, '/a').querySelector<HTMLButtonElement>('[data-fav-star]')?.click();
        await settle();
        expect(calls).toEqual([
            { path: '/config/common-commands/favorite', body: { command: '/a', favorite: false } },
        ]);
        expect(order(root)).toEqual(['/b']);
        expect(selected).toEqual([]);
    });
});
