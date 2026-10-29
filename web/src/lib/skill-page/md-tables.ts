import { parseInline, parseMarkdown, type Block, type Inline } from '../../opscenter/cells/notes/markdown';

export type MdPiece = { kind: 'md'; blocks: Block[] } | { kind: 'table'; head: Inline[][]; rows: Inline[][][] };

const DELIMITER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$|^\s*\|\s*:?-+:?\s*\|?\s*$/;

function cellsOf(line: string): string[] {
    let row = line.trim();
    if (row.startsWith('|')) row = row.slice(1);
    if (row.endsWith('|') && !row.endsWith('\\|')) row = row.slice(0, -1);
    return row.split(/(?<!\\)\|/).map((cell) => cell.replace(/\\\|/g, '|').trim());
}

export function splitTables(body: string): MdPiece[] {
    const lines = body.split('\n');
    const pieces: MdPiece[] = [];
    let run: string[] = [];
    let fence = false;
    const flush = (): void => {
        if (run.join('').trim()) pieces.push({ kind: 'md', blocks: parseMarkdown(run.join('\n')) });
        run = [];
    };
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i] as string;
        if (/^\s*(```|~~~)/.test(line)) fence = !fence;
        const next = lines[i + 1];
        if (!fence && line.includes('|') && next !== undefined && DELIMITER.test(next) && cellsOf(line).length === cellsOf(next).length) {
            flush();
            const head = cellsOf(line).map((cell) => parseInline(cell));
            const rows: Inline[][][] = [];
            i += 2;
            while (i < lines.length && (lines[i] as string).includes('|') && (lines[i] as string).trim() !== '') {
                rows.push(cellsOf(lines[i] as string).map((cell) => parseInline(cell)));
                i++;
            }
            i--;
            pieces.push({ kind: 'table', head, rows });
            continue;
        }
        run.push(line);
    }
    flush();
    return pieces;
}
