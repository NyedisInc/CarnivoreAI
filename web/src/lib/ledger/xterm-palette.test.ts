import { describe, expect, test } from 'vitest';
import { GRID_ROWS, PALETTE_GRID, XTERM_PALETTE, moveIndex, paletteIndexOf } from './xterm-palette';

describe('the xterm 256 palette', () => {
    test('has 256 lowercase hex entries in index order', () => {
        expect(XTERM_PALETTE).toHaveLength(256);
        XTERM_PALETTE.forEach((cell, i) => {
            expect(cell.index).toBe(i);
            expect(cell.hex).toMatch(/^#[0-9a-f]{6}$/);
        });
    });

    test.each([
        [0, '#000000'],
        [9, '#ff0000'],
        [16, '#000000'],
        [21, '#0000ff'],
        [44, '#00d7d7'],
        [196, '#ff0000'],
        [231, '#ffffff'],
        [232, '#080808'],
        [255, '#eeeeee'],
    ])('index %i is %s', (index, hex) => {
        expect(XTERM_PALETTE[index]?.hex).toBe(hex);
    });

    test('the sorted grid shows each distinct hex exactly once, keeping the lowest index', () => {
        const hexes = PALETTE_GRID.map((c) => c.hex);
        expect(PALETTE_GRID).toHaveLength(249);
        expect(new Set(hexes).size).toBe(249);
        expect(new Set(hexes)).toEqual(new Set(XTERM_PALETTE.map((c) => c.hex)));
        for (const cell of PALETTE_GRID) expect(cell.index).toBe(paletteIndexOf(cell.hex));
        const indexes = PALETTE_GRID.map((c) => c.index);
        expect(indexes).toContain(9);
        expect(indexes).not.toContain(196);
        expect(indexes).not.toContain(16);
    });

    test('the last column is short, and arrows never land on its empty slots', () => {
        const at = (p: number) => PALETTE_GRID[p]?.index as number;
        const last = PALETTE_GRID.length - 1;
        expect(last % GRID_ROWS).toBe(8);
        expect(moveIndex(at(last), 'ArrowDown')).toBe(at(last));
        const rowOne = at(last - 7);
        expect(moveIndex(rowOne, 'ArrowDown')).toBe(at(last - 6));
        const belowLast = at(last - GRID_ROWS);
        expect(moveIndex(belowLast, 'ArrowDown')).toBe(at(last - GRID_ROWS + 1));
        const lowLeft = at(last - GRID_ROWS + 5);
        expect(moveIndex(lowLeft, 'ArrowRight')).toBe(lowLeft);
    });

    test('a dropped duplicate has no cell and does not move', () => {
        expect(moveIndex(196, 'ArrowDown')).toBe(196);
    });

    test('the neutrals are grouped first, white at the top to black at the bottom', () => {
        const grey = (hex: string) => hex[1] === hex[3] && hex[3] === hex[5];
        const greys = PALETTE_GRID.slice(0, 32);
        expect(greys[0]?.hex).toBe('#ffffff');
        expect(greys[31]?.hex).toBe('#000000');
        expect(new Set(greys.map((c) => c.hex)).size).toBe(32);
        expect(greys.every((c) => grey(c.hex))).toBe(true);
    });

    test('a duplicate colour marks its first index; unknown and null mark none', () => {
        expect(paletteIndexOf('#000000')).toBe(0);
        expect(paletteIndexOf('#123456')).toBe(-1);
        expect(paletteIndexOf(null)).toBe(-1);
    });

    test('arrow keys walk the sorted grid and stop at its edges', () => {
        const at = (p: number) => PALETTE_GRID[p]?.index as number;
        expect(moveIndex(at(0), 'ArrowLeft')).toBe(at(0));
        expect(moveIndex(at(0), 'ArrowUp')).toBe(at(0));
        expect(moveIndex(at(0), 'ArrowDown')).toBe(at(1));
        expect(moveIndex(at(0), 'ArrowRight')).toBe(at(GRID_ROWS));
        expect(moveIndex(at(GRID_ROWS), 'ArrowLeft')).toBe(at(0));
        expect(moveIndex(at(GRID_ROWS - 1), 'ArrowDown')).toBe(at(GRID_ROWS - 1));
        const last = PALETTE_GRID.length - 1;
        expect(moveIndex(at(last), 'ArrowRight')).toBe(at(last));
    });
});
