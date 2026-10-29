/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MenuNode } from '../drawer-tabs/add-component-menu';

const shown: MenuNode[][] = [];
const calls: string[] = [];
const styleCalls: Array<[string, unknown]> = [];
let hue: number | null | undefined = 145;

vi.mock('../item-menu/open.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../item-menu/open.svelte')>();
    const { itemMenu } = await import('../item-menu/registry');
    return {
        ...real,
        openItemMenu: (type: never, ctx: never) => {
            const built = itemMenu(type, ctx, { close: () => { calls.push('close'); }, glyph: () => '' });
            if (!built) return false;
            shown.push(built.nodes);
            return true;
        },
        closeItemMenu: () => { calls.push('close'); },
    };
});
vi.mock('../companies', () => ({
    companyById: (id: number) => (id === 2 ? { id: 2, name: 'Acme', hue } : undefined),
    companyList: () => [{ id: 2, name: 'Acme', hue }],
    setCompanyColor: vi.fn(async (id: number, color: string | null) => { calls.push(`company ${id} ${color}`); }),
}));
vi.mock('../project-colors/store.svelte', () => ({ projectColorOf: (id: number | null) => (id === 5 ? '#6c799f' : null) }));
vi.mock('./interaction-globals', () => ({
    announce: () => {},
    announceFailure: (text: string) => { calls.push(`fail ${text}`); },
    applyGroups: () => { calls.push('apply'); },
    reasonOf: (e: unknown) => String((e as Error).message),
    usableGroups: () => ({ groupByUuid: (u: string) => (u === 'g1' ? { name: 'work', colour: 'teal', animation: 'pulse' } : null) }),
    hg: () => ({
        API: { setSessionGroupStyle: vi.fn(async (u: string, style: unknown) => { styleCalls.push([u, style]); return {}; }) },
        CloudeWeb: {
            layouts: {
                get: (u: string) => (u === 'L1' ? { name: 'pair', colour: 'indigo', gradient: 'tide', animation: 'shimmer' } : null),
                setStyle: vi.fn(async (u: string, style: unknown) => { styleCalls.push([u, style]); }),
            },
        },
    }),
}));

import { companyTint, projectTint } from './tint';
import { openColorMenu, writeColor } from './heading-color-actions';

beforeEach(() => {
    shown.length = 0;
    calls.length = 0;
    styleCalls.length = 0;
    hue = 145;
});

describe('row tinting', () => {
    it('a project and a company wear the color they were given', () => {
        expect(projectTint('p:5')).toBe('#6c799f');
        expect(companyTint(2)).toBe('oklch(0.74 0.09 145)');
    });

    it('nothing is stamped when no color was chosen (the drawer draws the 56/56/56 default from CSS)', () => {
        expect(projectTint('p:9')).toBeUndefined();
        hue = null;
        expect(companyTint(2)).toBeUndefined();
        hue = 145;
        expect(companyTint(null)).toBeUndefined();
    });
});

describe('the company kebab', () => {
    it('carries a colors entry between rename and delete, and a pick writes the hex', async () => {
        const { openItemMenu } = await import('../item-menu/open.svelte');
        expect(openItemMenu('company', { key: 'c:2', anchor: {} as Element }, {} as Element)).toBe(true);
        const entries = shown[0]!;
        const at = entries.findIndex((e) => e.swatches);
        expect(at).toBeGreaterThan(entries.findIndex((e) => e.id === 'rename-company'));
        expect(at).toBeLessThan(entries.findIndex((e) => e.id === 'delete-company'));
        entries[at]!.swatches!.onPick('#956b8b');
        await vi.waitFor(() => expect(calls).toContain('company 2 #956b8b'));
        expect(calls[0]).toBe('close');
    });

    it('offers "no color" only once a color is set', async () => {
        const { openItemMenu } = await import('../item-menu/open.svelte');
        openItemMenu('company', { key: 'c:2', anchor: {} as Element }, {} as Element);
        expect(shown[0]!.some((e) => e.id === 'clear-company-color')).toBe(true);
        hue = null;
        openItemMenu('company', { key: 'c:2', anchor: {} as Element }, {} as Element);
        expect(shown[1]!.some((e) => e.id === 'clear-company-color')).toBe(false);
    });
});

describe('group and layout writes', () => {
    it('a group pick is a flat color that keeps the animation', async () => {
        expect(await writeColor('group', 'g1', '#796589', 'work')).toBe(true);
        expect(styleCalls).toEqual([['g1', { colour: '#796589', gradient: null, animation: 'pulse' }]]);
    });

    it('a layout menu draws the shared row plus the older popup entry, and a pick clears the gradient', async () => {
        expect(openColorMenu({} as Element, 'layout', 'L1')).toBe(true);
        const entries = shown[0]!;
        expect(entries.filter((e) => e.swatches)).toHaveLength(1);
        expect(entries.some((e) => e.id === 'color-style')).toBe(true);
        entries.find((e) => e.swatches)!.swatches!.onPick('#845b6e');
        await vi.waitFor(() => expect(styleCalls).toEqual([['L1', { colour: '#845b6e', gradient: null, animation: 'shimmer' }]]));
    });

    it('an unknown layout opens nothing', () => {
        expect(openColorMenu({} as Element, 'layout', 'nope')).toBe(false);
        expect(shown).toHaveLength(0);
    });
});

describe('one picker', () => {
    const SRC = path.resolve(process.cwd(), 'src');

    function sources(dir: string): string[] {
        return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
            const full = path.join(dir, e.name);
            if (e.isDirectory()) return sources(full);
            return /\.(svelte|ts)$/.test(e.name) && !/\.test\.ts$/.test(e.name) ? [full] : [];
        });
    }

    it('no component opens a native color input; the shared in page picker replaced it (26ad3d66d)', () => {
        const owners = sources(SRC)
            .filter((f) => /type="color"/.test(fs.readFileSync(f, 'utf8')))
            .map((f) => path.relative(SRC, f))
            .filter((f) => !f.startsWith('lib/ledger/'));
        expect(owners).toEqual([]);
    });

    it('the shared menu driver draws every colors entry with that component', () => {
        const menu = fs.readFileSync(path.join(SRC, 'lib/drawer-tabs/CascadeMenu.svelte'), 'utf8');
        expect(menu).toContain("import ProjectColorRow from '../project-colors/ProjectColorRow.svelte'");
        expect((menu.match(/<ProjectColorRow/g) ?? []).length).toBe(1);
    });
});
