import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { browserChrome } from './recent-chrome';

interface StubEl {
    id: string;
    textContent: string;
    style: { display: string };
    dataset: Record<string, string>;
    attrs: Record<string, string>;
    classes: Set<string>;
    listeners: Array<() => void>;
    setAttribute(name: string, value: string): void;
    classList: { toggle(name: string, on: boolean): void };
    addEventListener(type: string, fn: () => void): void;
}

let requested: string[] = [];
let byId: Record<string, StubEl> = {};
let savedDocument: unknown;

function el(id: string): StubEl {
    const stub: StubEl = {
        id,
        textContent: '',
        style: { display: '' },
        dataset: {},
        attrs: {},
        classes: new Set<string>(),
        listeners: [],
        setAttribute(name, value) { this.attrs[name] = String(value); },
        classList: {
            toggle(name: string, on: boolean) {
                if (on) stub.classes.add(name);
                else stub.classes.delete(name);
            },
        },
        addEventListener(_type, fn) { this.listeners.push(fn); },
    };
    return stub;
}

function fixture(id: string): StubEl {
    const found = byId[id];
    expect(found, `no stub element for ${id}`).toBeDefined();
    return found as StubEl;
}

beforeEach(() => {
    requested = [];
    byId = {
        'recent-sessions-count': el('recent-sessions-count'),
        'recent-sessions-section': el('recent-sessions-section'),
        'recent-show-deleted-toggle': el('recent-show-deleted-toggle'),
        'recent-sessions-list': el('recent-sessions-list'),
    };
    savedDocument = (globalThis as { document?: unknown }).document;
    (globalThis as { document?: unknown }).document = {
        getElementById(id: string) {
            requested.push(id);
            return byId[id] || null;
        },
    };
});

afterEach(() => {
    (globalThis as { document?: unknown }).document = savedDocument;
});

describe('the collapse the user set survives every repaint', () => {
    test('NOTHING here ever reaches the list container', () => {
        const chrome = browserChrome();
        chrome.setCount('2 recent', 'ok');
        chrome.setSectionVisible(true);
        chrome.setArchiveToggle(true, 'hide archived sessions');
        chrome.bindArchiveToggle(() => {});
        expect(requested).not.toContain('recent-sessions-list');
        expect(fixture('recent-sessions-list').style.display).toBe('');
    });

    test('repeated repaints leave the list container untouched', () => {
        const chrome = browserChrome();
        for (let i = 0; i < 12; i++) chrome.setSectionVisible(i % 2 === 0);
        expect(requested).not.toContain('recent-sessions-list');
    });
});

describe('the section shows and hides the way the legacy renderer did', () => {
    test('visible clears display, hidden sets none', () => {
        const chrome = browserChrome();
        chrome.setSectionVisible(false);
        expect(fixture('recent-sessions-section').style.display).toBe('none');
        chrome.setSectionVisible(true);
        expect(fixture('recent-sessions-section').style.display).toBe('');
    });

    test('the count carries the state it is reporting, not just a number', () => {
        const chrome = browserChrome();
        chrome.setCount('cannot determine', 'probe_unavailable');
        expect(fixture('recent-sessions-count').textContent).toBe('cannot determine');
        expect(fixture('recent-sessions-count').attrs['data-state']).toBe('probe_unavailable');
    });

    test('a missing element is a no-op, never a throw', () => {
        byId = {};
        const chrome = browserChrome();
        expect(() => {
            chrome.setCount('x', 'ok');
            chrome.setSectionVisible(true);
            chrome.setArchiveToggle(true, 'x');
            chrome.bindArchiveToggle(() => {});
        }).not.toThrow();
    });
});

describe('the archive filter is one listener with the latest handler', () => {
    test('the pressed state, the class and the title all move together', () => {
        const chrome = browserChrome();
        const toggle = fixture('recent-show-deleted-toggle');
        chrome.setArchiveToggle(true, 'hide archived sessions');
        expect(toggle.attrs['aria-pressed']).toBe('true');
        expect(toggle.classes.has('is-on')).toBe(true);
        expect(toggle.attrs.title).toBe('hide archived sessions');
        chrome.setArchiveToggle(false, 'show archived sessions');
        expect(toggle.attrs['aria-pressed']).toBe('false');
        expect(toggle.classes.has('is-on')).toBe(false);
    });

    test('remounting does NOT stack listeners', () => {
        const toggle = fixture('recent-show-deleted-toggle');
        for (let i = 0; i < 5; i++) browserChrome().bindArchiveToggle(() => {});
        expect(toggle.listeners).toHaveLength(1);
    });

    test('and the LATEST handler is the one that runs, not the first', () => {
        const fired: string[] = [];
        browserChrome().bindArchiveToggle(() => fired.push('first'));
        browserChrome().bindArchiveToggle(() => fired.push('second'));
        browserChrome().bindArchiveToggle(() => fired.push('third'));
        fixture('recent-show-deleted-toggle').listeners.forEach((fn) => fn());
        expect(fired).toEqual(['third']);
    });
});
