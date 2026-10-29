
export interface PaletteCell {
    index: number;
    hex: string;
}

const ANSI_16 = [
    '#000000', '#cd0000', '#00cd00', '#cdcd00', '#0000ee', '#cd00cd', '#00cdcd', '#e5e5e5',
    '#7f7f7f', '#ff0000', '#00ff00', '#ffff00', '#5c5cff', '#ff00ff', '#00ffff', '#ffffff',
];

const CUBE_LEVELS = [0, 95, 135, 175, 215, 255];

function channel(value: number): string {
    return value.toString(16).padStart(2, '0');
}

export function xtermHex(index: number): string {
    if (index < 16) return ANSI_16[index] as string;
    if (index < 232) {
        const n = index - 16;
        const r = CUBE_LEVELS[Math.floor(n / 36)] as number;
        const g = CUBE_LEVELS[Math.floor(n / 6) % 6] as number;
        const b = CUBE_LEVELS[n % 6] as number;
        return `#${channel(r)}${channel(g)}${channel(b)}`;
    }
    const grey = 8 + (index - 232) * 10;
    return `#${channel(grey)}${channel(grey)}${channel(grey)}`;
}

export const XTERM_PALETTE: readonly PaletteCell[] = Object.freeze(
    Array.from({ length: 256 }, (_, index) => ({ index, hex: xtermHex(index) })),
);

export const GRID_ROWS = 16;

function hsl(hex: string): { h: number; s: number; l: number } {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as [number, number, number];
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const l = (max + min) / 2;
    const d = max - min;
    if (d === 0) return { h: 0, s: 0, l };
    const s = d / (1 - Math.abs(2 * l - 1));
    let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h = (h * 60 + 360) % 360;
    return { h, s, l };
}

function buildGrid(): PaletteCell[] {
    const isGrey = (c: PaletteCell) => c.hex[1] === c.hex[3] && c.hex[3] === c.hex[5];
    const seen = new Set<string>();
    const key = (c: PaletteCell) => ({ c, ...hsl(c.hex) });
    const distinct = XTERM_PALETTE.filter((c) => !seen.has(c.hex) && seen.add(c.hex));
    const greys = distinct.filter(isGrey).map(key);
    const colours = distinct.filter((c) => !isGrey(c)).map(key);
    greys.sort((a, b) => b.l - a.l || a.c.index - b.c.index);
    colours.sort((a, b) => a.h - b.h || b.l - a.l || a.c.index - b.c.index);
    const out = greys.map((g) => g.c);
    for (let i = 0; i < colours.length; i += GRID_ROWS) {
        const column = colours.slice(i, i + GRID_ROWS);
        column.sort((a, b) => b.l - a.l || b.s - a.s || a.c.index - b.c.index);
        out.push(...column.map((x) => x.c));
    }
    return out;
}

export const PALETTE_GRID: readonly PaletteCell[] = Object.freeze(buildGrid());

const POSITION: readonly number[] = XTERM_PALETTE.map((c) => PALETTE_GRID.findIndex((g) => g.index === c.index));

export function paletteIndexOf(hex: string | null): number {
    if (hex === null) return -1;
    return XTERM_PALETTE.findIndex((cell) => cell.hex === hex);
}

export function moveIndex(index: number, key: string): number {
    const at = POSITION[index] as number;
    if (at < 0) return index;
    const row = at % GRID_ROWS;
    let to = at;
    if (key === 'ArrowUp' && row > 0) to = at - 1;
    else if (key === 'ArrowDown' && row < GRID_ROWS - 1) to = at + 1;
    else if (key === 'ArrowLeft') to = at - GRID_ROWS;
    else if (key === 'ArrowRight') to = at + GRID_ROWS;
    const cell = PALETTE_GRID[to];
    return to >= 0 && cell ? cell.index : index;
}
