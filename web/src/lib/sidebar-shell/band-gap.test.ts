import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const CSS = fs.readFileSync(path.join(ROOT, 'client', 'css', 'session-sidebar-band-structure.css'), 'utf8');
const SPACE = { '--oc-space-0-5': 2, '--oc-space-1': 4, '--oc-space-1-5': 6, '--oc-space-2': 8, '--oc-space-4': 16 } as const;
type Density = 'cozy' | 'compact';

function px(block: string, token: string): number {
    if (token in SPACE) return SPACE[token as keyof typeof SPACE];
    const m = block.match(new RegExp(`${token}:\\s*([^;]+);`));
    expect(m, `${token} declared`).not.toBeNull();
    const v = m![1]!.trim();
    if (/^\d+px$/.test(v)) return parseInt(v, 10);
    const sum = v.match(/^calc\(var\((--[\w-]+)\) \+ var\((--[\w-]+)\)\)$/);
    if (sum) return px(block, sum[1]!) + px(block, sum[2]!);
    const ref = v.match(/^var\((--[\w-]+)\)$/);
    expect(ref, `${token} is a px or one var()`).not.toBeNull();
    const name = ref![1]!;
    if (name in SPACE) return SPACE[name as keyof typeof SPACE];
    return px(block, name);
}

const ROOT_BLOCK = CSS.match(/:root \{[^}]*\}/)![0];
const COMPACT_BLOCK = CSS.match(/\[data-density="compact"\] \{[^}]*\}/)![0];
const BLOCKS: Record<Density, string> = { cozy: ROOT_BLOCK, compact: `${COMPACT_BLOCK}\n${ROOT_BLOCK}` };

describe('drawer band gap', () => {
    it.each([['cozy', 6, 14], ['compact', 3, 9]] as const)('%s: closed nested %ipx, closed top-level %ipx', (d, nested, top) => {
        expect(px(BLOCKS[d], '--sidebar-band-gap-closed')).toBe(nested);
        expect(px(BLOCKS[d], '--sidebar-band-gap-top-closed')).toBe(top);
        expect(px(BLOCKS[d], '--sidebar-band-gap-closed')).toBeGreaterThan(px(BLOCKS[d], '--sidebar-row-gap'));
    });

    it.each([['cozy', 28, 36], ['compact', 8, 14]] as const)('%s: open nested %ipx, open top-level %ipx', (d, nested, top) => {
        expect(px(BLOCKS[d], '--sidebar-band-gap')).toBe(nested);
        expect(px(BLOCKS[d], '--sidebar-band-gap-top')).toBe(top);
    });

    it('top-level lists (including LAYOUTS) take the level-up gaps, nested lists the base ones', () => {
        const topRule = CSS.match(/\.session-sidebar-list,\s*\.session-sidebar-companies > \.session-sidebar-group__body \{[^}]*\}/)?.[0] ?? '';
        expect(topRule).toContain('--_gap-closed: var(--sidebar-band-gap-top-closed)');
        expect(topRule).toContain('--_gap-open: var(--sidebar-band-gap-top)');
        const layoutsRule = CSS.match(/\.session-sidebar-group\[data-group="layouts"\] > \.session-sidebar-group__body \{[^}]*\}/)?.[0] ?? '';
        expect(layoutsRule).toContain('--_gap-closed: var(--sidebar-band-gap-top-closed)');
        expect(layoutsRule).toContain('--_gap-open: var(--sidebar-band-gap-top)');
        const nestedRule = CSS.match(/\.session-sidebar-groups-block > \.session-sidebar-group__body,\s*\.session-sidebar-projects > \.session-sidebar-group__body \{[^}]*\}/)?.[0] ?? '';
        expect(nestedRule).toContain('--_gap-closed: var(--sidebar-band-gap-closed)');
        expect(nestedRule).toContain('--_gap-open: var(--sidebar-band-gap)');
    });

    it('the lists space their bands by their own closed gap', () => {
        const rule = CSS.match(/\.session-sidebar-list,[^{]*\{\s*row-gap[^}]*\}/)?.[0] ?? '';
        expect(rule).toContain('row-gap: var(--_gap-closed)');
    });

    it('an open band or open company keeps its list\'s open gap under itself', () => {
        const rule = CSS.match(/[^{}]*\[data-collapsed="0"\]:not\(:last-child\)[^{]*\{[^}]*\}/)?.[0] ?? '';
        expect(rule).toContain('margin-bottom: calc(var(--_gap-open) - var(--_gap-closed))');
        expect(rule).toContain('[data-company-open="1"]');
    });
});
