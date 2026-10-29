import { describe, expect, it } from 'vitest';
import { entryNodes, spaced } from './entries';

const noGlyph = (): string => '';

describe('entryNodes', () => {
    it('keeps order, draws a hairline above each later group and the destructive entry last in the danger tone', () => {
        const entries = spaced([
            [{ label: 'rename', id: 'rename-group', icon: 'rename', onPick: () => {} }, { label: 'add', id: 'add-members', onPick: () => {}, children: () => [{ id: 'x', label: 'x', run: () => {} }] }],
            [{ label: 'sleep', id: 'sleep', onPick: () => {} }],
            [{ label: 'remove', id: 'delete-group', danger: true, onPick: () => {} }],
        ]);
        const nodes = entryNodes(entries, noGlyph, () => {});
        expect(nodes.map((n) => n.id)).toEqual(['rename-group', 'add-members', 'sleep', 'delete-group']);
        expect(nodes.map((n) => !!n.sep)).toEqual([false, false, true, true]);
        expect(nodes[3]!.danger).toBe(true);
        expect(nodes[1]!.children).toHaveLength(1);
    });

    it('an inert entry carries its reason and a glyph comes from the row menu set', () => {
        const nodes = entryNodes([{ label: 'move up', id: 'move-up', icon: 'move-up', blocked: 'already first', onPick: () => {} }], (icon) => `<svg data-g="${icon}"></svg>`, () => {});
        expect(nodes[0]).toMatchObject({ blocked: 'already first', glyphHtml: '<svg data-g="move-up"></svg>' });
    });

    it('a color entry is a swatch row that reports the pressed key', () => {
        const picks: string[] = [];
        const nodes = entryNodes([{ label: '', id: 'project-color', onPick: () => {}, colors: { value: '#4e69ba', allowNone: true, onPick: (k) => picks.push(k) } }], noGlyph, () => {});
        expect(nodes[0]!.swatches).toMatchObject({ value: '#4e69ba', allowNone: true });
        nodes[0]!.swatches!.onPick('rose');
        expect(picks).toEqual(['rose']);
    });

    it('an entry closes the menu first, then acts; a branch leaf closes it too', () => {
        const log: string[] = [];
        const nodes = entryNodes(
            [
                { label: 'rename', id: 'rename', onPick: () => log.push('act') },
                { label: 'add', id: 'add', onPick: () => {}, children: () => [{ id: 'leaf', label: 'leaf', run: () => log.push('leaf') }] },
            ],
            noGlyph,
            () => log.push('close'),
        );
        nodes[0]!.run!();
        nodes[1]!.children![0]!.run!();
        expect(log).toEqual(['close', 'act', 'leaf', 'close']);
    });

    it('two entries with one id stay distinct', () => {
        const nodes = entryNodes([{ label: 'a', id: 'x', onPick: () => {} }, { label: 'b', id: 'x', onPick: () => {} }], noGlyph, () => {});
        expect(new Set(nodes.map((n) => n.id)).size).toBe(2);
    });
});
