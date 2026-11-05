import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { ACTIONS } from '../../../../client/js/keymap/actions.js';
import { buildTree, countLeaves, entryForItem, groupPath, TOP_GROUPS } from '../../../../client/js/keymap/tree.js';
import { flatItemIds, MENU_GROUPS, UNDRAWN_ITEM_IDS } from '../../../../client/js/keymap/menu-tree.js';
import { LETTERS } from '../../../../client/js/menu-keys.js';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { viewTree } from './keymap-view';

const catalog = enCatalog as Record<string, string>;
const t = (key: string): string => catalog[key] ?? key;
const root = new URL('../../../../', import.meta.url);
const read = (rel: string): string => readFileSync(new URL(rel, root), 'utf8');

interface Node { id: string; labelKey: string; children?: Node[]; action?: { id: string }; itemId?: string }
const tree = buildTree(ACTIONS) as Node[];

function at(...ids: string[]): Node | undefined {
    let level: Node[] | undefined = tree;
    let node: Node | undefined;
    for (const id of ids) {
        node = level?.find((n) => n.id === id);
        level = node?.children;
    }
    return node;
}

describe('menus nest as branches', () => {
    test('sidebar > agent row menu > rename is a path, and its leaf carries the rename verb and its letter', () => {
        const menu = at('menus', 'sidebar', 'agent-row');
        expect(menu?.children?.length).toBeGreaterThan(10);
        const leaf = menu!.children!.find((n) => n.itemId === 'rename')!;
        expect(leaf.action?.id).toBe('menu.rename');
        expect(catalog[leaf.labelKey]).toBe('rename');
        expect(catalog[at('menus', 'sidebar', 'agent-row')!.labelKey]).toBe('agent row menu');
    });

    test('the same verb sits under every menu that draws it, with the same letter', () => {
        const homes = [['menus', 'sidebar', 'agent-row'], ['menus', 'sidebar', 'browser-row'], ['menus', 'sidebar', 'group-heading', 'customize']];
        for (const home of homes) {
            const leaf = at(...home)!.children!.find((n) => n.action?.id === 'menu.rename' || n.action?.id === 'menu.close');
            expect(leaf, home.join('>')).toBeTruthy();
        }
    });

    test('top groups come out in the stated order and every branch counts its leaves', () => {
        expect(tree.map((n) => n.id)).toEqual([...TOP_GROUPS]);
        expect(countLeaves(at('menus')!)).toBe(countLeaves(at('menus', 'sidebar')!) + countLeaves(at('menus', 'widgets')!));
        expect(countLeaves(at('app', 'layout-tabs')!)).toBe(9);
    });

    test('every non-menu action has a place, every menu verb is reached, and every branch has words in the catalog', () => {
        expect(ACTIONS.filter((a: { id: string }) => !a.id.startsWith('menu.') && groupPath(a) === null).map((a: { id: string }) => a.id)).toEqual([]);
        const reached = new Set<string>();
        const walk = (n: Node): void => (n.children ? n.children.forEach(walk) : void reached.add(n.action!.id));
        tree.forEach(walk);
        expect(ACTIONS.filter((a: { id: string }) => a.id.startsWith('menu.') && !reached.has(a.id)).map((a: { id: string }) => a.id)).toEqual([]);
        const check = (n: Node): void => {
            expect(catalog[n.labelKey], n.labelKey).toBeTruthy();
            n.children?.forEach(check);
        };
        tree.forEach(check);
    });
});

describe('a menu cascade is a branch under its menu', () => {
    test('customize is a branch of the group heading menu holding rename, add, color, icon and filter', () => {
        const branch = at('menus', 'sidebar', 'group-heading', 'customize');
        expect(branch?.children?.map((n) => n.itemId)).toEqual(['rename-group', 'add-members', 'colour', 'group-icon', 'group-rule']);
        expect(catalog[branch!.labelKey]).toBe('customize');
    });
});

describe('the menu tree is the menus as they are built', () => {
    test('every item a menu lists is in that menu\'s source, so a dropped or mistyped item goes red', () => {
        for (const group of MENU_GROUPS) {
            for (const menu of group.menus) {
                const src = menu.files.map((f: string) => read(f)).join('\n');
                for (const id of flatItemIds(menu.items)) {
                    const prefix = id.includes(':') ? `${id.split(':')[0]}:` : null;
                    const found = src.includes(`'${id}'`) || src.includes(`"${id}"`) || (prefix !== null && src.includes(prefix));
                    expect(found, `${group.id} > ${menu.id}: ${id}`).toBe(true);
                }
            }
        }
    });

    test('the captured menus (goldens) draw no lettered item the tree leaves out', () => {
        const golden = (file: string): Record<string, unknown> => JSON.parse(read(`web/src/lib/item-menu/__goldens__/${file}`));
        const ids = (value: unknown): string[] => {
            const list = (Array.isArray(value) ? value : (value as { entries?: unknown[] }).entries ?? []) as { id: string; key?: string; children?: unknown[] }[];
            return list.flatMap((e) => [...(e.key ? [e.id] : []), ...(e.children ? ids(e.children) : [])]);
        };
        const items = (menuId: string): Set<string> => new Set(flatItemIds(MENU_GROUPS.flatMap((g: { menus: { id: string; items: unknown[] }[] }) => g.menus).find((m: { id: string }) => m.id === menuId)!.items));
        const against: [string, string, string][] = [
            ['row-menus.json', 'session', 'agent-row'], ['row-menus.json', 'browser', 'browser-row'], ['row-menus.json', 'page', 'page-row'],
            ['heading-menus.json', 'project', 'project-heading'], ['heading-menus.json', 'company', 'company-heading'], ['heading-menus.json', 'group', 'group-heading'],
            ['heading-menus.json', 'section', 'section-heading'], ['heading-menus.json', 'leader', 'leader'],
        ];
        for (const [file, prefix, menuId] of against) {
            const listed = items(menuId);
            for (const [name, value] of Object.entries(golden(file))) {
                if (!name.startsWith(prefix)) continue;
                for (const id of ids(value).filter((i) => entryForItem(i))) expect(listed.has(id), `${file} > ${name}: ${id} is missing from ${menuId}`).toBe(true);
            }
        }
    });

    test('every lettered item is in a menu or in the stated list no menu draws, and that list stays true', () => {
        const placed = new Set<string>(MENU_GROUPS.flatMap((g: { menus: { items: unknown[] }[] }) => g.menus.flatMap((m) => flatItemIds(m.items))));
        const lettered: string[] = LETTERS.flatMap((e: { ids: string[] }) => e.ids);
        expect(lettered.filter((id) => !placed.has(id) && !UNDRAWN_ITEM_IDS.includes(id))).toEqual([]);
        for (const id of UNDRAWN_ITEM_IDS) {
            expect(lettered, id).toContain(id);
            expect(placed.has(id), `${id} is drawn by a menu now: take it off the undrawn list`).toBe(false);
        }
    });
});

describe('a search keeps the tree and opens only what matched', () => {
    const base = { pressed: null, family: 'mac' as const, t };

    test('rename finds the rename items under their menus, nothing else, and asks every branch open', () => {
        const view = viewTree({ ...base, text: 'rename' });
        expect(view.searching).toBe(true);
        const ids: string[] = [];
        const walk = (n: { id: string; children?: readonly unknown[] }): void => (n.children ? (n.children as { id: string }[]).forEach(walk) : void ids.push(n.id));
        view.nodes.forEach(walk);
        expect(ids).toContain('sidebar/agent-row/rename');
        expect(ids).toContain('sidebar/group-heading/customize/rename-group');
        expect(ids.every((id) => /rename|^sidebar\/sidebar\.row\.rename|sidebar\.row\.rename/.test(id) || /rename/i.test(id))).toBe(true);
        expect(view.nodes.map((n) => n.id)).toContain('menus');
        expect(view.nodes.map((n) => n.id)).not.toContain('desktop');
    });

    test('with nothing asked the whole tree comes back, not searching', () => {
        const view = viewTree({ ...base, text: '' });
        expect(view.searching).toBe(false);
        expect(view.nodes.map((n) => n.id)).toEqual([...TOP_GROUPS]);
        expect(view.total).toBeGreaterThan(250);
    });

    test('a pressed chord keeps only what holds it', () => {
        const view = viewTree({ ...base, text: '', pressed: 'cmd+k' });
        expect(view.total).toBe(1);
        expect(view.nodes[0]?.id).toBe('app');
    });
});
