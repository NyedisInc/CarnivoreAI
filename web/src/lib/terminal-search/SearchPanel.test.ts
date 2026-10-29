/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

import { mountTerminalSearch, terminalSearchController, unmountTerminalSearch } from './mount-search';
import { t } from '../i18n/index.svelte';
import { uiPrefs } from '../ui/prefs.svelte';
import { settle } from './search-controller-harness';
import type { SearchController } from './search-controller.svelte';
import type { SearchHost } from './search-host';

interface Calls {
    pane: string[];
    focusTerm: number;
    find: string[];
}

interface Harness {
    controller: SearchController;
    calls: Calls;
    panel: () => HTMLElement;
    input: () => HTMLInputElement;
    headerBtn: () => HTMLButtonElement;
    key: (on: Element | Document, init: KeyboardEventInit & { key: string }) => KeyboardEvent;
}

function setup(over?: Partial<SearchHost>): Harness {
    document.body.innerHTML = `
        <button type="button" id="terminalSearchBtn" class="btn-icon"></button>
        <div id="terminal-screen" class="screen active">
            <div class="terminal-container" id="terminal-container">
                <div id="terminal"></div>
            </div>
        </div>`;
    const container = document.getElementById('terminal-container') as HTMLElement;

    const calls: Calls = { pane: [], focusTerm: 0, find: [] };
    container.addEventListener('keydown', (e) => calls.pane.push((e as KeyboardEvent).key));

    const term = {
        buffer: { active: { type: 'normal', baseY: 0, cursorY: 0, viewportY: 0, length: 0 } },
    };
    const host: SearchHost = {
        term: () => term,
        sessionId: () => 'ses_a',
        onTerminal: () => () => {},
        agentFamily: () => 'claude',
        engine: () => ({
            attach: () => {},
            find: (q) => calls.find.push(q),
            next: () => {},
            prev: () => {},
            clear: () => {},
            onResults: () => () => {},
            predicate: () => () => true,
        }),
        history: () => null,
        promptScan: () => ({ scan: () => [], layoutTicks: () => [], currentOrdinalFor: () => 0 }),
        isRule: () => undefined,
        modalOpen: () => false,
        terminalScreenActive: () => true,
        focusTerm: () => {
            calls.focusTerm += 1;
        },
    };
    const controller = mountTerminalSearch({ ...host, ...(over ?? {}) });
    if (!controller) throw new Error('the panel did not mount');
    flushSync();

    return {
        controller,
        calls,
        panel: () => document.querySelector('.terminal-search-panel') as HTMLElement,
        input: () => document.querySelector('.terminal-search__input') as HTMLInputElement,
        headerBtn: () => document.getElementById('terminalSearchBtn') as HTMLButtonElement,
        key: (on, init) => {
            const e = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
            on.dispatchEvent(e);
            return e;
        },
    };
}

let h: Harness | null = null;

beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
    unmountTerminalSearch();
    h = null;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('mounting', () => {
    test('the panel and the rail host are inside the terminal container', () => {
        h = setup();
        const container = document.getElementById('terminal-container') as HTMLElement;
        expect(h.panel().parentElement).toBe(container);
        expect(container.querySelector('.terminal-prompt-rail-host')).not.toBeNull();
        expect(container.querySelector('#terminal')).not.toBeNull();
    });

    test('the prompt header stands down while a tabbed head row hosts it (#533), and is the page one', () => {
        h = setup();
        const container = document.getElementById('terminal-container') as HTMLElement;
        expect(terminalSearchController()).toBe(h.controller);
        expect(container.querySelector('.prompt-header-root')).not.toBeNull();
        h.controller.headerHosted = true;
        flushSync();
        expect(container.querySelector('.prompt-header-root')).toBeNull();
        h.controller.headerHosted = false;
        flushSync();
        expect(container.querySelector('.prompt-header-root')).not.toBeNull();
    });

    test('it paints closed, and Cmd+F opens it', () => {
        h = setup();
        expect(h.panel().classList.contains('is-open')).toBe(false);
        const e = h.key(document, { key: 'f', metaKey: true });
        flushSync();
        expect(h.controller.isOpen()).toBe(true);
        expect(h.panel().classList.contains('is-open')).toBe(true);
        expect(e.defaultPrevented).toBe(true);
    });

    test('the header button toggles it, wired in JS and never in markup', () => {
        h = setup();
        h.headerBtn().click();
        expect(h.controller.isOpen()).toBe(true);
        h.headerBtn().click();
        expect(h.controller.isOpen()).toBe(false);
        expect(h.headerBtn().getAttribute('onclick')).toBeNull();
    });

    test('the panel takes its top from the stylesheet, never an inline one', () => {
        h = setup();
        h.controller.open();
        flushSync();
        expect(h.panel().style.top).toBe('');
    });
});

describe('autofocus', () => {
    test('the field is focused by the time open() returns, with no flush from the caller', () => {
        h = setup();
        h.controller.open();
        expect(document.activeElement).toBe(h.input());
    });

    test('the panel is already painted open at the moment focus is called', () => {
        h = setup();
        const seen: boolean[] = [];
        const input = h.input();
        const real = input.focus.bind(input);
        vi.spyOn(input, 'focus').mockImplementation((opts) => {
            seen.push(input.closest('.terminal-search-panel')!.classList.contains('is-open'));
            real(opts);
        });
        h.controller.open();
        expect(seen).toEqual([true]);
    });

    test('focus lands before the history load resolves, not after', () => {
        h = setup({ history: () => ({ ensureLoaded: () => new Promise(() => {}) }) });
        h.controller.open();
        expect(document.activeElement).toBe(h.input());
        expect(h.controller.history).toBe('pending');
    });

    test('re-opening refocuses and SELECTS the existing text', () => {
        h = setup();
        h.controller.open();
        const input = h.input();
        input.value = 'needle';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        (document.getElementById('terminal') as HTMLElement).focus();

        h.key(document, { key: 'f', metaKey: true });
        expect(document.activeElement).toBe(input);
        expect(input.selectionStart).toBe(0);
        expect(input.selectionEnd).toBe('needle'.length);
    });
});

describe('the shield', () => {
    test('typing in the field never reaches the pane', () => {
        h = setup();
        h.controller.open();
        flushSync();
        for (const key of ['r', 'm', ' ', '-', 'f', 'Backspace', 'Home', 'x']) {
            h.key(h.input(), { key });
        }
        expect(h.calls.pane).toEqual([]);
    });

    test('Enter, Shift+Enter, the arrows and Escape never reach it either', () => {
        h = setup();
        h.controller.open();
        flushSync();
        h.key(h.input(), { key: 'Enter' });
        h.key(h.input(), { key: 'Enter', shiftKey: true });
        h.key(h.input(), { key: 'ArrowUp' });
        h.key(h.input(), { key: 'ArrowDown' });
        h.key(h.input(), { key: 'Escape' });
        expect(h.calls.pane).toEqual([]);
    });

    test('NEGATIVE CONTROL: the pane spy DOES see a key typed at the pane', () => {
        h = setup();
        h.controller.open();
        flushSync();
        h.key(document.getElementById('terminal') as Element, { key: 'q' });
        expect(h.calls.pane).toEqual(['q']);
    });

    test('a shielded character is not prevented, so the field still receives it', () => {
        h = setup();
        h.controller.open();
        flushSync();
        const e = h.key(h.input(), { key: 'r' });
        expect(e.defaultPrevented).toBe(false);
    });
});

describe('closing', () => {
    test('Escape in the field closes the panel and gives the pane its focus back', () => {
        h = setup();
        h.controller.open();
        flushSync();
        h.key(h.input(), { key: 'Escape' });
        flushSync();
        expect(h.controller.isOpen()).toBe(false);
        expect(h.calls.focusTerm).toBe(1);
        expect(h.panel().classList.contains('is-open')).toBe(false);
    });

    test('NEGATIVE: Escape typed AT THE PANE does not close the panel', () => {
        h = setup();
        h.controller.open();
        flushSync();
        h.key(document.getElementById('terminal') as Element, { key: 'Escape' });
        expect(h.controller.isOpen()).toBe(true);
        expect(h.calls.focusTerm).toBe(0);
    });

    test('the close control closes it', () => {
        h = setup();
        h.controller.open();
        flushSync();
        (h.panel().querySelector('[aria-label="close search (esc)"]') as HTMLButtonElement).click();
        flushSync();
        expect(h.controller.isOpen()).toBe(false);
    });

    test('a destroyed session closes it', () => {
        h = setup();
        h.controller.open();
        window.dispatchEvent(new Event('session-destroyed'));
        expect(h.controller.isOpen()).toBe(false);
    });
});

describe('what the row shows', () => {
    test('the field is labelled for a screen reader and takes no autocorrect', () => {
        h = setup();
        const input = h.input();
        expect(input.getAttribute('aria-label')).toBe('search this session');
        expect(input.getAttribute('autocapitalize')).toBe('off');
        expect(input.getAttribute('spellcheck')).toBe('false');
    });

    test('the counter is a polite live region', () => {
        h = setup();
        expect(
            (document.querySelector('.terminal-search__count') as HTMLElement).getAttribute(
                'aria-live',
            ),
        ).toBe('polite');
    });

    test('NEGATIVE: no deep-dive control renders even for a fully wired archive lookup', async () => {
        h = setup({
            deepDive: () => ({
                hrefFor: async () => '/archive/p/1?q=hazard',
                diagnose: async () => ({ href: '/archive/p/1?q=hazard', reason: null }),
                open: async () => true,
            }),
        } as any);
        h.controller.open();
        h.controller.query = 'hazard';
        await settle();
        flushSync();
        expect(document.querySelector('.terminal-search__deep')).toBeNull();
    });

    test('the mount is reversible: unmount takes the panel and the chord away', () => {
        h = setup();
        const controller = h.controller;
        unmountTerminalSearch();
        expect(document.querySelector('.terminal-search-panel')).toBeNull();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', metaKey: true }));
        expect(controller.isOpen()).toBe(false);
    });
});

describe('the prompts-only toggle', () => {
    const toggle = (): HTMLButtonElement => {
        const el = document.querySelector('[data-search-key="prompts-only"]');
        if (!el) throw new Error('no prompts-only toggle in the panel');
        return el as HTMLButtonElement;
    };

    beforeEach(() => {
        const seen = new Map<string, string>();
        Object.defineProperty(globalThis, 'localStorage', {
            value: {
                getItem: (k: string) => (seen.has(k) ? seen.get(k) : null),
                setItem: (k: string, v: string) => {
                    seen.set(k, v);
                },
            },
            configurable: true,
            writable: true,
        });
        uiPrefs.resetForTests();
    });

    afterEach(() => {
        uiPrefs.resetForTests();
    });

    test('it opens unpressed, because nothing has been chosen yet', () => {
        h = setup();
        h.controller.open();
        flushSync();
        expect(toggle().getAttribute('aria-pressed')).toBe('false');
    });

    test('clicking it flips the pressed state; the tooltip text does not change', () => {
        h = setup();
        h.controller.open();
        flushSync();
        const wrap = () => toggle().closest('.terminal-search__tip') as HTMLElement;
        expect(wrap().getAttribute('data-tooltip')).toBe(t('search.prompts_only.toggle'));
        toggle().click();
        flushSync();
        expect(toggle().getAttribute('aria-pressed')).toBe('true');
        expect(wrap().getAttribute('data-tooltip')).toBe(t('search.prompts_only.toggle'));
    });

    test('its accessible name is a resolved catalog string, not a key', () => {
        h = setup();
        h.controller.open();
        flushSync();
        const label = toggle().getAttribute('aria-label');
        expect(label).toBe(t('search.prompts_only.toggle'));
        expect(label).not.toBe('search.prompts_only.toggle');
    });

    test('the button carries no title: the wrapping span is the ONLY tooltip (issue #650)', () => {
        h = setup();
        h.controller.open();
        flushSync();
        expect(toggle().getAttribute('title')).toBeNull();
    });

    test('a codex session is not disabled (issue #631)', () => {
        h = setup({ agentFamily: () => 'codex' });
        h.controller.open();
        flushSync();
        expect(toggle().disabled).toBe(false);
    });

    test('NEGATIVE: a claude session is not disabled', () => {
        h = setup({ agentFamily: () => 'claude' });
        h.controller.open();
        flushSync();
        expect(toggle().disabled).toBe(false);
    });
});

describe('the direction toggle, and the frozen prompt header beside it', () => {
    beforeEach(() => {
        const seen = new Map<string, string>();
        Object.defineProperty(globalThis, 'localStorage', {
            value: {
                getItem: (k: string) => (seen.has(k) ? seen.get(k) : null),
                setItem: (k: string, v: string) => {
                    seen.set(k, v);
                },
            },
            configurable: true,
            writable: true,
        });
        uiPrefs.resetForTests();
    });

    afterEach(() => {
        uiPrefs.resetForTests();
    });

    const toggle = (): HTMLButtonElement => {
        const el = document.querySelector('[data-search-key="direction"]');
        if (!el) throw new Error('no direction toggle in the panel');
        return el as HTMLButtonElement;
    };

    test('it opens pressed, because bottom up is the default', () => {
        h = setup();
        h.controller.open();
        flushSync();
        expect(toggle().getAttribute('aria-pressed')).toBe('true');
    });

    test('clicking it flips the direction and the pressed state', () => {
        h = setup();
        h.controller.open();
        flushSync();
        toggle().click();
        flushSync();
        expect(h.controller.direction).toBe('top_down');
        expect(toggle().getAttribute('aria-pressed')).toBe('false');
    });

    test('its copy is a resolved catalog string, not a key', () => {
        h = setup();
        h.controller.open();
        flushSync();
        const label = toggle().getAttribute('aria-label');
        expect(label).toBe(t('search.direction.toggle'));
        expect(label).not.toBe('search.direction.toggle');
        expect(toggle().getAttribute('title')).toBe(t('search.direction.bottom_up'));
    });

    test('the two chevrons point the way the viewport will actually travel', () => {
        h = setup();
        h.controller.open();
        flushSync();
        const upward = (sel: string): boolean => {
            const path = document.querySelector(`${sel} path`);
            return (path?.getAttribute('d') ?? '').startsWith('M12 10');
        };
        expect(upward('[data-search-key="next"]')).toBe(true);
        expect(upward('[data-search-key="prev"]')).toBe(false);
        toggle().click();
        flushSync();
        expect(upward('[data-search-key="next"]')).toBe(false);
        expect(upward('[data-search-key="prev"]')).toBe(true);
    });

    test('the frozen prompt header is mounted into the terminal container', () => {
        h = setup();
        const container = document.getElementById('terminal-container') as HTMLElement;
        expect(container.querySelector('.prompt-header-root')).not.toBeNull();
    });
});
