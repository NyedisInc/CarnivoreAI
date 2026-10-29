/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { browserSearchHost } from './search-host';
import { installKeyRouting } from './search-keys';

describe('cell search targeting', () => {
    test('explicit controller overrides the primary without mutating it', () => {
        const primary = { term: { cols: 80 }, _sessionId: () => 'primary' };
        const secondary = { term: { cols: 120 }, _sessionId: () => 'secondary' };
        Object.assign(window, { TerminalController: primary });
        const host = browserSearchHost(secondary);
        expect(host.term()).toBe(secondary.term);
        expect(host.sessionId()).toBe('secondary');
        secondary.term = { cols: 100 };
        expect(host.term()?.cols).toBe(100);
        expect(browserSearchHost().term()).toBe(primary.term);
        delete (window as unknown as Record<string, unknown>).TerminalController;
    });

    test('one keyboard router resolves ownership at each gesture', () => {
        const opened: string[] = [];
        const make = (id: string) => ({
            isOpen: () => false, containsTarget: () => false, alternate: () => false,
            screenActive: () => true, modalOpen: () => false,
            open: () => opened.push(id), close() {}, step() {}, jump() {},
        });
        let selected = make('a');
        const stop = installKeyRouting(() => selected, document);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', metaKey: true }));
        selected = make('b');
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', metaKey: true }));
        stop();
        expect(opened).toEqual(['a', 'b']);
    });
});

test('two open panels isolate queries, results, stepping and clear', async () => {
    const { readFileSync } = await import('node:fs');
    const { SearchController } = await import('./search-controller.svelte');
    const records: Array<{ queries: string[]; clears: number; emit: (r: unknown) => void }> = [];
    class Addon {
        record = { queries: [] as string[], clears: 0, emit: (_r: unknown) => {} };
        constructor() { records.push(this.record); }
        onDidChangeResults(cb: (r: unknown) => void): void { this.record.emit = cb; }
        findNext(q: string): boolean { this.record.queries.push(q); return true; }
        findPrevious(q: string): boolean { return this.findNext(q); }
        clearDecorations(): void { this.record.clears++; }
    }
    const globals = window as unknown as Record<string, unknown>;
    globals.SearchAddon = { SearchAddon: Addon };
    new Function('window', 'document', readFileSync('../client/js/terminal-search-engine.js', 'utf8'))(window, document);
    const make = (id: string) => ({
        term: { loadAddon() {}, buffer: { active: { type: 'normal', length: 0 } } },
        _sessionId: () => id,
    });
    const a = new SearchController(browserSearchHost(make('a')));
    const b = new SearchController(browserSearchHost(make('b')));
    try {
        a.open();
        b.open();
        a.query = 'alpha'; a.runQuery();
        b.query = 'beta'; b.runQuery();
        a.step('next');
        expect(records[0]!.queries).toEqual(['alpha', 'alpha']);
        expect(records[1]!.queries).toEqual(['beta']);
        records[0]!.emit({ resultIndex: 0, resultCount: 4 });
        records[1]!.emit({ resultIndex: 1, resultCount: 9 });
        expect(a.results?.resultCount).toBe(4);
        expect(b.results?.resultCount).toBe(9);
        a.close();
        expect(records[0]!.clears).toBe(1);
        expect(records[1]!.clears).toBe(0);
        expect(b.results?.resultCount).toBe(9);
    } finally {
        a.close(); b.close();
        a.rail.dispose(); b.rail.dispose();
        delete globals.TerminalSearchEngine;
        delete globals.SearchAddon;
    }
});

test('toggleCellSearch shows then hides one slot panel, and reads back reactively', async () => {
    const { registerCellSearch, toggleCellSearch, cellSearchOpen } = await import('./cell-search');
    const container = document.createElement('div');
    document.body.appendChild(container);
    const client = { term: { loadAddon() {}, buffer: { active: { type: 'normal', length: 0 } } }, _sessionId: () => 'x' };
    const stop = registerCellSearch('terminal:toggle', client as never, container);
    expect(cellSearchOpen('terminal:toggle')).toBe(false);
    expect(toggleCellSearch('terminal:toggle')).toBe(true);
    expect(cellSearchOpen('terminal:toggle')).toBe(true);
    toggleCellSearch('terminal:toggle');
    expect(cellSearchOpen('terminal:toggle')).toBe(false);
    stop();
    expect(toggleCellSearch('terminal:toggle')).toBe(false);
    expect(cellSearchOpen('terminal:toggle')).toBeNull();
    container.remove();
});
