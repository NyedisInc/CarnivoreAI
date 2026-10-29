import { describe, expect, it } from 'vitest';
import { nestByParent, pruneTree, type TreeNode } from './lineage-tree';

interface Item { id: number; p?: number | null }

const nest = (items: Item[]): Array<TreeNode<Item>> => nestByParent(items, (x) => x.id, (x) => x.p ?? null);
const shape = (nodes: Array<TreeNode<Item>>): unknown[] => nodes.map((n) => (n.children.length ? [n.item.id, shape(n.children)] : n.item.id));

describe('nestByParent', () => {
    it('is the identity on a flat list: every item a root, in order, no children', () => {
        const items = [{ id: 3 }, { id: 1 }, { id: 2, p: null }];
        const roots = nest(items);
        expect(roots.map((n) => n.item)).toEqual(items);
        expect(roots.every((n) => n.children.length === 0)).toBe(true);
    });

    it('nests to any depth and keeps the input order among siblings', () => {
        expect(shape(nest([{ id: 1 }, { id: 5, p: 1 }, { id: 2, p: 1 }, { id: 3, p: 2 }, { id: 4 }]))).toEqual([[1, [5, [2, [3]]]], 4]);
    });

    it('roots an item whose parent is not in the list, or is itself', () => {
        expect(shape(nest([{ id: 1, p: 99 }, { id: 2, p: 2 }]))).toEqual([1, 2]);
    });

    it('roots every member of a cycle and still nests what hangs off it', () => {
        expect(shape(nest([{ id: 1, p: 2 }, { id: 2, p: 1 }, { id: 3, p: 1 }]))).toEqual([[1, [3]], 2]);
    });

    it('keeps the first of a repeated id', () => {
        const items = [{ id: 1 }, { id: 1, p: 7 }];
        expect(nest(items).map((n) => n.item)).toEqual([items[0]]);
    });
});

describe('pruneTree', () => {
    it('keeps matches and the path to them, drops the rest', () => {
        const roots = nest([{ id: 1 }, { id: 2, p: 1 }, { id: 3, p: 2 }, { id: 4, p: 1 }, { id: 5 }]);
        expect(shape(pruneTree(roots, (x) => x.id === 3))).toEqual([[1, [[2, [3]]]]]);
        expect(shape(pruneTree(roots, (x) => x.id === 5 || x.id === 1))).toEqual([1, 5]);
    });
});
