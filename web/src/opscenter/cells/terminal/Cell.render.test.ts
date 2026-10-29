/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Cell from './Cell.svelte';
import CellHost from '../../CellHost.svelte';
import { adoptPane, paneCustodian, releaseHeldPane, releasePane } from './adopt';
import { inputFocus } from '../../lib/input-focus.svelte';
import { isPrimaryInstance } from './meta';
import { TERMINAL_META, metaFor } from '../../engine/meta';
import type { SlotId } from '../../engine/types';
import { homeLayout, terminalLayout } from '../../engine/layout.svelte';
import { flushSave } from '../../engine/persist';
import { SESSION_INDEX_KEY } from '../../engine/session-layouts';

const PRIMARY = 'terminal:@primary';

function buildPage(): { grid: HTMLElement; pane: HTMLElement } {
    document.body.innerHTML =
        '<div id="terminal-screen" class="screen active">' +
        '<div id="terminal-grid">' +
        '<div class="terminal-container" id="terminal-container"><div id="terminal"></div></div>' +
        '</div>' +
        '</div>';
    return {
        grid: document.getElementById('terminal-grid') as HTMLElement,
        pane: document.getElementById('terminal-container') as HTMLElement,
    };
}

function body(): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    return host;
}

afterEach(() => {
    releaseHeldPane();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('the pane is adopted on mount and given back on unmount', () => {
    test('a primary cell takes the live pane into its own body', () => {
        const { grid, pane } = buildPage();
        expect(pane.parentElement).toBe(grid);

        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();

        expect(target.contains(pane)).toBe(true);
        expect(document.getElementById('terminal-container')).toBe(pane);
        expect(pane.parentElement).not.toBe(grid);

        unmount(app, { outro: false });
        flushSync();
        expect(pane.parentElement).toBe(grid);
        expect(document.getElementById('terminal-container')).toBe(pane);
    });

    test('the pane the cell gives back is the node it was handed, not a copy', () => {
        const { grid, pane } = buildPage();
        const inner = document.getElementById('terminal') as HTMLElement;
        const marker = { seen: true };
        (pane as unknown as { marker?: unknown }).marker = marker;

        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        unmount(app, { outro: false });
        flushSync();

        const back = document.getElementById('terminal-container') as HTMLElement;
        expect(back).toBe(pane);
        expect((back as unknown as { marker?: unknown }).marker).toBe(marker);
        expect(back.firstElementChild).toBe(inner);
        expect(back.parentElement).toBe(grid);
    });

    test('a cell mounted with no pane on the page draws and takes nothing', () => {
        document.body.innerHTML = '';
        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        expect(paneCustodian()).toBe(null);
        expect(target.querySelector('.cc-pane')).not.toBe(null);
        unmount(app, { outro: false });
    });
});

describe('no changes rail in a terminal cell (issue #1406, folded into the file browser)', () => {
    test('a bound primary session draws the pane with no rail beside it', () => {
        buildPage();
        const ctl = { _sessionId: () => 'ses_1' };
        (globalThis as { TerminalController?: unknown }).TerminalController = ctl;
        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        expect(target.querySelector('.cc-pane')).not.toBe(null);
        expect(target.querySelector('[data-git-rail]')).toBe(null);
        unmount(app, { outro: false });
        delete (globalThis as { TerminalController?: unknown }).TerminalController;
    });
});

describe('one node, one owner', () => {
    test('a second live host is refused and the first keeps the pane', () => {
        const { pane } = buildPage();
        const first = body();
        const second = body();
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

        const release = adoptPane(first);
        expect(release).not.toBe(null);
        expect(pane.parentElement).toBe(first);

        expect(adoptPane(second)).toBe(null);
        expect(pane.parentElement).toBe(first);
        expect(warn).toHaveBeenCalledTimes(1);

        release?.();
        expect(pane.parentElement).toBe(document.getElementById('terminal-grid'));
    });

    test('the same host adopting twice is a no-op with no second release', () => {
        const { pane } = buildPage();
        const host = body();
        const first = adoptPane(host);
        expect(first).not.toBe(null);
        expect(adoptPane(host)).toBe(null);
        expect(pane.parentElement).toBe(host);
        expect(paneCustodian()).toBe(host);
        first?.();
        expect(paneCustodian()).toBe(null);
    });

    test('releasing a host that never held it moves nothing', () => {
        const { grid, pane } = buildPage();
        const host = body();
        const other = body();
        adoptPane(host);
        expect(releasePane(other)).toBe(false);
        expect(pane.parentElement).toBe(host);
        expect(releasePane(host)).toBe(true);
        expect(pane.parentElement).toBe(grid);
    });

    test('releaseHeldPane is the second stop and is idempotent', () => {
        const { grid, pane } = buildPage();
        const host = body();
        adoptPane(host);
        expect(releaseHeldPane()).toBe(true);
        expect(pane.parentElement).toBe(grid);
        expect(releaseHeldPane()).toBe(false);
        expect(pane.parentElement).toBe(grid);
    });
});

describe('the height ladder governs chrome, never the grid', () => {
    test('the strip step prints the line and hides the pane without giving it up', () => {
        const { pane } = buildPage();
        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 90, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();

        const host = target.querySelector('.cc-pane') as HTMLElement;
        expect(target.textContent).toContain('too short');
        expect(host.hasAttribute('hidden')).toBe(true);
        expect(host.contains(pane)).toBe(true);
        unmount(app, { outro: false });
        flushSync();
    });

    test('above the strip threshold the pane is shown and the line is not drawn', () => {
        buildPage();
        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        const host = target.querySelector('.cc-pane') as HTMLElement;
        expect(host.hasAttribute('hidden')).toBe(false);
        expect(target.textContent).not.toContain('too short');
        unmount(app, { outro: false });
        flushSync();
    });
});

describe('input focus is the browser\'s own focus, gated on holding the pane', () => {
    afterEach(() => {
        inputFocus.release(PRIMARY);
    });

    function focusInto(el: Element): void {
        el.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
        flushSync();
    }

    function focusAway(el: Element): void {
        el.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
        flushSync();
    }

    test('mounting claims nothing; focus entering the pane is what claims', () => {
        buildPage();
        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        expect(paneCustodian()).not.toBe(null);
        expect(inputFocus.owner).toBe(null);

        const host = target.querySelector('.cc-pane') as HTMLElement;
        expect(host).toBeTruthy();
        focusInto(host);
        expect(inputFocus.owner).toBe(PRIMARY);
        expect(host.getAttribute('data-input-owner')).toBe('true');

        focusAway(host);
        expect(inputFocus.owner).toBe(null);
        expect(host.getAttribute('data-input-owner')).toBe(null);

        unmount(app, { outro: false });
        flushSync();
        expect(paneCustodian()).toBe(null);
    });

    test('a cell that goes away while focused gives the record back', () => {
        buildPage();
        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        focusInto(target.querySelector('.cc-pane') as HTMLElement);
        expect(inputFocus.owner).toBe(PRIMARY);

        unmount(app, { outro: false });
        flushSync();
        expect(inputFocus.owner).toBe(null);
    });

    test('a cell refused the pane refuses the claim, and does not unlight the holder', () => {
        buildPage();
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const held = body();
        const release = adoptPane(held);
        expect(release).not.toBe(null);

        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        expect(warn).toHaveBeenCalled();
        expect(paneCustodian()).toBe(held);

        focusInto(target.querySelector('.cc-pane') as HTMLElement);
        expect(inputFocus.owner).toBe(null);

        unmount(app, { outro: false });
        flushSync();
        expect(paneCustodian()).toBe(held);
        release?.();
    });

    test('a viewer slot has no pane host of its own to be focused into', () => {
        buildPage();
        const target = body();
        const id = 'terminal:adopted:cloude_api';
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(id), instance: id },
        });
        flushSync();
        expect(target.querySelector('.cc-pane')).toBe(null);
        expect(inputFocus.owner).toBe(null);
        unmount(app, { outro: false });
        flushSync();
    });

    test('a page with no pane leaves the record empty rather than guessing', () => {
        document.body.innerHTML = '';
        const target = body();
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(PRIMARY), instance: PRIMARY },
        });
        flushSync();
        expect(paneCustodian()).toBe(null);
        focusInto(target.querySelector('.cc-pane') as HTMLElement);
        expect(inputFocus.owner).toBe(null);
        unmount(app, { outro: false });
        flushSync();
    });
});

describe('a slot that is not the primary is a VIEWER, and this cell delegates', () => {
    test('it never touches the live pane and renders the viewer component', () => {
        const { grid, pane } = buildPage();
        const target = body();
        const id = 'terminal:adopted:cloude_api';
        const app = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(id), instance: id },
        });
        flushSync();
        expect(pane.parentElement).toBe(grid);
        expect(paneCustodian()).toBe(null);
        expect(target.querySelector('.cc-pane')).toBe(null);
        expect(target.querySelector('.oc-tv')).not.toBe(null);
        expect(target.querySelector('.oc-tv-head')).not.toBe(null);
        unmount(app, { outro: false });
        flushSync();
    });

    test('the page it is told it is on picks WHICH cell, and names its control', () => {
        buildPage();
        const target = body();
        const id = 'terminal:adopted:cloude_api';
        const home = mount(Cell, {
            target,
            props: { width: 1200, height: 800, meta: metaFor(id), instance: id },
        });
        flushSync();
        expect(target.querySelector('.oc-tv'), 'home drew no viewer').not.toBe(null);
        expect(target.querySelector('.oc-tl'), 'home drew a live terminal').toBe(null);
        expect(target.querySelector('.oc-tv-action')?.textContent?.trim()).toBe('open');
        unmount(home, { outro: false });
        flushSync();

        const onTerminal = mount(Cell, {
            target,
            props: {
                width: 1200,
                height: 800,
                meta: metaFor(id),
                instance: id,
                page: 'terminal' as const,
            },
        });
        flushSync();
        expect(target.querySelector('.oc-tl'), 'the terminal page drew no live terminal')
            .not.toBe(null);
        expect(target.querySelector('.oc-tv'), 'the terminal page drew a read-only viewer')
            .toBe(null);
        expect(target.querySelector('.oc-tl-action')).toBe(null);
        expect(target.textContent).not.toContain('make primary');
        unmount(onTerminal, { outro: false });
        flushSync();
    });
});

describe('what the cell says about the session it shows', () => {
    test('the primary is told apart from a viewer without importing the engine model', () => {
        expect(isPrimaryInstance(PRIMARY)).toBe(true);
        expect(isPrimaryInstance('terminal:ses_a1')).toBe(false);
        expect(isPrimaryInstance('themes')).toBe(false);
        expect(metaFor(PRIMARY).chrome).toBe('card');
        expect(metaFor('terminal:ses_a1').chrome).toBe('card');
        expect(TERMINAL_META.heightStates.map((step) => step.name)).toEqual(['strip', 'pane']);
    });
});

describe('THE WHOLE THREAD: the store tells CellHost the page, CellHost tells the cell', () => {
    test('the home page says open; the terminal page offers no such control', () => {
        const had = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
        (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        };
        try {
        buildPage();
        const target = body();
        const id = 'terminal:adopted:cloude_api' as SlotId;

        const onHome = mount(CellHost, { target, props: { id, store: homeLayout } });
        flushSync();
        expect(target.querySelector('.oc-tv-action')?.textContent?.trim()).toBe('open');
        unmount(onHome, { outro: false });
        flushSync();

        const onTerminal = mount(CellHost, { target, props: { id, store: terminalLayout } });
        flushSync();
        expect(target.querySelector('.oc-tl-action')).toBe(null);
        unmount(onTerminal, { outro: false });
        flushSync();
        } finally {
            (globalThis as { ResizeObserver?: unknown }).ResizeObserver = had;
        }
    });
});

describe('the two pages are two layouts with two storage keys', () => {
  test('the terminal page opens on one primary slot and the home page does not', () => {
    const slots = terminalLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
    expect(slots).toEqual([PRIMARY]);
    const homeSlots = homeLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
    expect(homeSlots).not.toContain(PRIMARY);
    expect(homeSlots.length).toBeGreaterThan(1);
  });

  test('saving one page writes its own key and leaves the other untouched', () => {
    localStorage.clear();
    terminalLayout.bindSession('cloude_render');
    const layouts = (): string[] =>
      Object.keys(localStorage).filter((k) => k.includes('opscenter') && k !== SESSION_INDEX_KEY);
    terminalLayout.toggleCollapsed(PRIMARY);
    flushSave();
    const keys = layouts();
    expect(keys.length).toBe(1);
    const [terminalKey] = keys;
    expect(terminalKey).toContain('terminal');
    expect(terminalKey).toContain('cloude_render');

    homeLayout.toggleCollapsed('themes');
    flushSave();
    const both = layouts().sort();
    expect(both.length).toBe(2);
    expect(both.filter((k) => k.includes('terminal')).length).toBe(1);
    const stored = JSON.parse(localStorage.getItem(terminalKey as string) as string);
    const storedSlots = stored.rows.flatMap((row: { slots: { id: string }[] }) => row.slots.map((s: { id: string }) => s.id));
    expect(storedSlots).toEqual([PRIMARY]);
    terminalLayout.bindSession('');
    localStorage.clear();
  });
});
