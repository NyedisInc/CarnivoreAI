
export const GRID = 5;

export interface IdenticonShape {
    cells: Array<[number, number]>;
    tone: number;
}

export function fnv1a(text: string): number {
    let hash = 0x811c9dc5;
    for (let i = 0; i < text.length; i += 1) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash >>> 0;
}

export function identicon(handle: string): IdenticonShape {
    const key = handle.trim().toLowerCase();
    const hash = fnv1a(key);
    const more = fnv1a(`${key}#`);
    const cells: Array<[number, number]> = [];
    let bit = 0;
    for (let y = 0; y < GRID; y += 1) {
        for (let x = 0; x < 3; x += 1) {
            if ((hash >>> bit) & 1) {
                cells.push([x, y]);
                if (x < 2) cells.push([GRID - 1 - x, y]);
            }
            bit += 1;
        }
    }
    if (cells.length === 0) cells.push([2, 2]);
    cells.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
    return { cells, tone: (more >>> 28) & 3 };
}

export function identiconMarkup(handle: string, size: number): string {
    const shape = identicon(handle);
    const rects = shape.cells.map(([x, y]) => `<rect x="${x}" y="${y}" width="1" height="1"/>`).join('');
    return `<svg class="ident ident--${shape.tone}" data-tone="${shape.tone}" width="${size}" height="${size}" viewBox="0 0 ${GRID} ${GRID}" `
        + `aria-hidden="true" focusable="false" shape-rendering="crispEdges">${rects}</svg>`;
}
