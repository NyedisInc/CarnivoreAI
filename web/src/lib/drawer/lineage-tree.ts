
export interface TreeNode<T> {
    item: T;
    children: Array<TreeNode<T>>;
}

export function nestByParent<T, K>(
    items: ReadonlyArray<T>, idOf: (item: T) => K, parentOf: (item: T) => K | null | undefined,
): Array<TreeNode<T>> {
    const nodes = new Map<K, TreeNode<T>>();
    for (const item of items) if (!nodes.has(idOf(item))) nodes.set(idOf(item), { item, children: [] });
    const parentIn = (item: T): K | null => {
        const p = parentOf(item);
        return p !== null && p !== undefined && p !== idOf(item) && nodes.has(p) ? p : null;
    };
    const cyclic = (item: T): boolean => {
        const self = idOf(item);
        const seen = new Set<K>([self]);
        let current = parentIn(item);
        while (current !== null) {
            if (current === self) return true;
            if (seen.has(current)) return false;
            seen.add(current);
            current = parentIn(nodes.get(current)!.item);
        }
        return false;
    };
    const roots: Array<TreeNode<T>> = [];
    for (const item of items) {
        const node = nodes.get(idOf(item))!;
        if (node.item !== item) continue;
        const parent = parentIn(item);
        if (parent === null || cyclic(item)) roots.push(node);
        else nodes.get(parent)!.children.push(node);
    }
    return roots;
}

export function pruneTree<T>(nodes: ReadonlyArray<TreeNode<T>>, keep: (item: T) => boolean): Array<TreeNode<T>> {
    const out: Array<TreeNode<T>> = [];
    for (const node of nodes) {
        const children = pruneTree(node.children, keep);
        if (keep(node.item) || children.length) out.push({ item: node.item, children });
    }
    return out;
}
