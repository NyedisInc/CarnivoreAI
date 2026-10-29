/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { ensurePanel, unmountPanel } from '../mount';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import TerminalBackgroundButton from './TerminalBackgroundButton.svelte';

installPopoverPolyfill();

const BACKGROUND_CONTAINER_ID = 'tbg-test-container';

interface Calls {
    uploaded: Array<{ name: string; file: File }>;
    cleared: string[];
}

const THEME = {
    id: 'carnivore',
    name: 'Carnivore',
    source: 'builtin',
    background: { image: 'background.png', dim: 0.8 },
    xterm: { background: '#0e1112', foreground: '#eaebed' },
};

const FLOOR = 0.79;

interface SetupOptions {
    stored?: Record<string, unknown> | null;
    uploadStatus?: number;
}

function setup(options: SetupOptions = {}) {
    document.body.innerHTML = `<div id="${BACKGROUND_CONTAINER_ID}"></div>`;

    const calls: Calls = { uploaded: [], cleared: [] };
    const overrides: Record<string, unknown> = {};
    if (options.stored) overrides.cloude_demo = options.stored;

    (globalThis as Record<string, unknown>).TerminalBackground = {
        DEFAULT_DIM: 0.8,
        minimumDim: () => FLOOR,
        getActiveSession: () => 'cloude_demo',
        getOverrides: () => overrides,
        setOverride: async () => ({}),
        uploadImage: async (name: string, file: File) => {
            if (options.uploadStatus) {
                const err = new Error('refused') as Error & { status: number };
                err.status = options.uploadStatus;
                throw err;
            }
            calls.uploaded.push({ name, file });
            return {};
        },
        clearImage: async (name: string) => {
            calls.cleared.push(name);
            return {};
        },
    };
    (globalThis as Record<string, unknown>).Themes = {
        listAll: () => [THEME],
        getActiveTerminalManifest: () => THEME,
    };
    ensurePanel(BACKGROUND_CONTAINER_ID, TerminalBackgroundButton as never, {});
    flushSync();

    const button = () => document.querySelector('.tbg-open') as HTMLButtonElement;
    const popover = () => document.querySelector('.tbg-pop') as HTMLElement | null;
    return {
        calls,
        button,
        popover,
        open() {
            button().click();
            flushSync();
        },
        key(key: string) {
            document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
            flushSync();
        },
        pointer(on: Node) {
            on.dispatchEvent(new Event('pointerdown', { bubbles: true }));
            flushSync();
        },
    };
}

afterEach(() => {
    unmountPanel(BACKGROUND_CONTAINER_ID);
    delete (globalThis as Record<string, unknown>).TerminalBackground;
    delete (globalThis as Record<string, unknown>).Themes;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('the button', () => {
    test('announces that it opens a dialog, and whether it is open', () => {
        const s = setup();
        expect(s.button().getAttribute('aria-haspopup')).toBe('dialog');
        expect(s.button().getAttribute('aria-expanded')).toBe('false');
        expect(s.popover()).toBeNull();

        s.open();
        expect(s.button().getAttribute('aria-expanded')).toBe('true');
        expect(s.popover()).not.toBeNull();
    });

    test('carries an accessible name from the catalog, not a bare glyph', () => {
        const s = setup();
        const label = s.button().getAttribute('aria-label') || '';
        expect(label.length).toBeGreaterThan(0);
        expect(label).not.toContain('terminal.background.');
    });
});

describe('closing', () => {
    test('escape closes it and focus goes back to the button', () => {
        const s = setup();
        s.open();
        s.key('Escape');
        expect(s.popover()).toBeNull();
        expect(s.button().getAttribute('aria-expanded')).toBe('false');
        expect(document.activeElement).toBe(s.button());
    });

    test('a pointer outside closes it and focus goes back to the button', () => {
        const s = setup();
        s.open();
        s.pointer(document.body);
        expect(s.popover()).toBeNull();
        expect(document.activeElement).toBe(s.button());
    });

    test('a pointer INSIDE keeps it open', () => {
        const s = setup();
        s.open();
        const inside = s.popover() as HTMLElement;
        s.pointer(inside);
        expect(s.popover()).not.toBeNull();
    });

    test('a second click on the button closes it, and focus stays there', () => {
        const s = setup();
        s.open();
        s.button().click();
        flushSync();
        expect(s.popover()).toBeNull();
        expect(document.activeElement).toBe(s.button());
    });
});

describe('the panel inside it', () => {
    test('the dim slider cannot go below the computed floor', () => {
        const s = setup();
        s.open();
        const range = s.popover()?.querySelector('input[type="range"]') as HTMLInputElement;
        expect(range).toBeTruthy();
        expect(range.min).toBe(String(Math.ceil(FLOOR * 100)));
        expect(range.max).toBe('100');
    });

    test('the floor is explained rather than left as a slider that will not move', () => {
        const s = setup();
        s.open();
        const text = s.popover()?.textContent || '';
        expect(text).toContain(String(Math.ceil(FLOOR * 100)));
    });

    test('choosing a file uploads that exact file for this session', () => {
        const s = setup();
        s.open();
        const input = s.popover()?.querySelector('input[type="file"]') as HTMLInputElement;
        expect(input).toBeTruthy();
        expect(input.getAttribute('accept')).toContain('image/png');

        const file = new File([new Uint8Array([1, 2, 3])], 'pic.png', { type: 'image/png' });
        Object.defineProperty(input, 'files', { value: [file], configurable: true });
        input.dispatchEvent(new Event('change', { bubbles: true }));
        flushSync();

        expect(s.calls.uploaded).toHaveLength(1);
        const sent = s.calls.uploaded[0]!;
        expect(sent.name).toBe('cloude_demo');
        expect(sent.file).toBe(file);
    });

    test('"use the theme image" deletes this session\'s own picture', async () => {
        const s = setup({ stored: { image: 'cloude_demo.png', dim: null, disabled: false } });
        s.open();
        const buttons = Array.from(
            s.popover()?.querySelectorAll('button.tbg__btn') || [],
        ) as HTMLButtonElement[];
        expect(buttons).toHaveLength(1);
        const clear = buttons[0]!;
        clear.click();
        await Promise.resolve();
        flushSync();
        expect(s.calls.cleared).toEqual(['cloude_demo']);
    });

    test('the clear control is absent when this session uploaded nothing', () => {
        const s = setup();
        s.open();
        expect(s.popover()?.querySelectorAll('button.tbg__btn')).toHaveLength(0);
    });

    test('a refused type says so, and says which refusal it was', async () => {
        const s = setup({ uploadStatus: 415 });
        s.open();
        const input = s.popover()?.querySelector('input[type="file"]') as HTMLInputElement;
        const file = new File([new Uint8Array([60])], 'x.svg', { type: 'image/svg+xml' });
        Object.defineProperty(input, 'files', { value: [file], configurable: true });
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await Promise.resolve();
        await Promise.resolve();
        flushSync();

        const bad = s.popover()?.querySelector('.tbg__note--bad');
        expect(bad).toBeTruthy();
        const text = bad?.textContent || '';
        expect(text).not.toContain('terminal.background.');
        expect(text).toContain('png');
    });

    test('a too-large upload gets the OTHER sentence', async () => {
        const s = setup({ uploadStatus: 413 });
        s.open();
        const input = s.popover()?.querySelector('input[type="file"]') as HTMLInputElement;
        const file = new File([new Uint8Array([1])], 'big.png', { type: 'image/png' });
        Object.defineProperty(input, 'files', { value: [file], configurable: true });
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await Promise.resolve();
        await Promise.resolve();
        flushSync();

        const text = s.popover()?.querySelector('.tbg__note--bad')?.textContent || '';
        expect(text).toContain('large');
        expect(text).not.toContain('png');
    });
});

describe('the menu-item presentation (issue #959)', () => {
    const mounted: ReturnType<typeof mount>[] = [];

    afterEach(async () => {
        for (const component of mounted.splice(0)) await unmount(component);
        document.body.replaceChildren();
    });

    test('draws a role=menuitem row with a visible label', () => {
        const target = document.createElement('div');
        document.body.append(target);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        mounted.push(mount(TerminalBackgroundButton as any, { target, props: { asMenuItem: true } }));
        flushSync();
        const button = target.querySelector('.tbg-open') as HTMLButtonElement;
        expect(button.getAttribute('role')).toBe('menuitem');
        expect(button.classList.contains('tbg-menuitem')).toBe(true);
        expect(button.textContent?.trim().length).toBeGreaterThan(0);
    });

    test('the default (asMenuItem absent) presentation carries no menuitem role or label text node', () => {
        const target = document.createElement('div');
        document.body.append(target);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        mounted.push(mount(TerminalBackgroundButton as any, { target, props: {} }));
        flushSync();
        const button = target.querySelector('.tbg-open') as HTMLButtonElement;
        expect(button.getAttribute('role')).toBeNull();
        expect(button.querySelector('.tbg-menuitem-label')).toBeNull();
    });
});
