import { describe, expect, it, vi } from 'vitest';

vi.mock('../file-drawer/file-drawer', () => ({ showFilesCell: vi.fn(() => true) }));
vi.mock('../open-files/open-bridge', () => ({ openFromPath: vi.fn(async () => undefined) }));
vi.mock('./api', () => ({ openOutside: vi.fn(async () => undefined) }));

import { findPathCandidates, looksLikePath } from './detect';
import { termPathNodes } from '../item-menu/menus/termpath';
import { showFilesCell } from '../file-drawer/file-drawer';
import { openFromPath } from '../open-files/open-bridge';
import { openOutside } from './api';

const texts = (line: string) => findPathCandidates(line).map((c) => c.text);

describe('path candidates on a row', () => {
    it('finds absolute, ~, relative and bare names with a line suffix', () => {
        expect(texts('error at /Users/a/x.py:12:3, see ~/notes.md and src/lib/a.ts')).toEqual(
            ['/Users/a/x.py:12:3', '~/notes.md', 'src/lib/a.ts']);
        expect(texts(' M README.md')).toEqual(['README.md']);
        expect(texts('-rw-r--r--  1 alex staff  120 Oct 31 12:00 package.json')).toEqual(['package.json']);
    });

    it('spans the printed text exactly and drops a sentence full stop', () => {
        const [c] = findPathCandidates('open docs/plan.md.');
        expect(c).toEqual({ text: 'docs/plan.md', start: 5, end: 17 });
    });

    it('never links a URL, a version or a plain word', () => {
        expect(texts('see https://example.com/a/b.html now')).toEqual([]);
        expect(texts('v1.16.5 r6 ok 3.14 done')).toEqual([]);
        expect(looksLikePath('/')).toBe(false);
        expect(looksLikePath('hello')).toBe(false);
    });
});

describe('the terminal path menu', () => {
    const file = { sessionId: 'ses_1', text: 'a.md:3', path: '/r/a.md', kind: 'file' as const, touch: false };

    it('offers carnivore first, then the browser and finder, for a file', () => {
        const nodes = termPathNodes(file);
        expect(nodes.map((n) => n.id)).toEqual(['open-carnivore', 'open-browser', 'show-finder']);
        expect(nodes.map((n) => n.label)).toEqual(['open in carnivore', 'open in browser', 'show in finder']);
    });

    it('offers the files browser and finder for a folder, and only carnivore on a phone', () => {
        expect(termPathNodes({ ...file, path: '/r/src', kind: 'dir' }).map((n) => n.id)).toEqual(['open-carnivore', 'show-finder']);
        expect(termPathNodes({ ...file, touch: true }).map((n) => n.id)).toEqual(['open-carnivore']);
    });

    it('each row reaches its opener', async () => {
        const [carnivore, browser, finder] = termPathNodes(file);
        carnivore?.run?.(); browser?.run?.(); finder?.run?.();
        termPathNodes({ ...file, kind: 'dir' })[0]?.run?.();
        await Promise.resolve(); await Promise.resolve();
        expect(openFromPath).toHaveBeenCalledWith('/r/a.md');
        expect(openOutside).toHaveBeenCalledWith('ses_1', 'a.md:3', 'browser');
        expect(openOutside).toHaveBeenCalledWith('ses_1', 'a.md:3', 'finder');
        expect(showFilesCell).toHaveBeenCalled();
    });
});
