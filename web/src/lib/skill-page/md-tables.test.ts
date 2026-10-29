import { describe, expect, it } from 'vitest';
import { splitTables } from './md-tables';

describe('splitTables', () => {
    it('turns a pipe table into a table piece between markdown runs', () => {
        const pieces = splitTables('intro\n\n| A | B |\n|---|:-:|\n| 1 | `x` |\n| 2 | y \\| z |\n\nafter');
        expect(pieces.map((p) => p.kind)).toEqual(['md', 'table', 'md']);
        const table = pieces[1];
        if (table?.kind !== 'table') throw new Error('no table');
        expect(table.head).toHaveLength(2);
        expect(table.rows).toHaveLength(2);
        expect(table.rows[1]?.[1]).toEqual([{ kind: 'text', text: 'y | z' }]);
    });
    it('leaves a table inside a code fence alone and a lone pipe line as text', () => {
        expect(splitTables('```\n| A |\n|---|\n| 1 |\n```').map((p) => p.kind)).toEqual(['md']);
        expect(splitTables('a | b\nplain').map((p) => p.kind)).toEqual(['md']);
    });
});
