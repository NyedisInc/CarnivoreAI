import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { closing } from '../widget-menu/model';
import type {
    BuiltItemMenu, ItemMenuContexts, ItemMenuContribution, ItemMenuEnv, ItemMenuType, ItemMenuTypeEntry,
} from './types';

export class ItemMenuError extends Error {}

const types = new Map<ItemMenuType, ItemMenuTypeEntry<never>>();
const contributions = new Map<ItemMenuType, ItemMenuContribution<never>[]>();

export function defineItemMenu<T extends ItemMenuType>(type: T, entry: ItemMenuTypeEntry<ItemMenuContexts[T]>): void {
    if (types.has(type)) throw new ItemMenuError(`item menu type "${type}" is already defined`);
    types.set(type, entry as ItemMenuTypeEntry<never>);
}

export function contributeItemMenu<T extends ItemMenuType>(type: T, contribution: ItemMenuContribution<ItemMenuContexts[T]>): () => void {
    const list = contributions.get(type) ?? [];
    if (list.some((c) => c.id === contribution.id)) throw new ItemMenuError(`item menu type "${type}" already has a contribution "${contribution.id}"`);
    list.push(contribution as ItemMenuContribution<never>);
    contributions.set(type, list);
    return () => {
        const now = contributions.get(type) ?? [];
        contributions.set(type, now.filter((c) => c !== (contribution as ItemMenuContribution<never>)));
    };
}

function mergeContributions(nodes: MenuNode[], groups: MenuNode[][]): MenuNode[] {
    const extra = groups.filter((g) => g.length);
    if (!extra.length) return nodes;
    let cut = nodes.length;
    for (let i = nodes.length - 1; i >= 0; i--) {
        if (!nodes[i]!.danger) break;
        cut = i;
        if (nodes[i]!.sep) break;
    }
    const before = nodes.slice(0, cut);
    const after = nodes.slice(cut);
    const added: MenuNode[] = [];
    for (const g of extra) g.forEach((n, i) => added.push(i === 0 && (before.length || added.length) ? { ...n, sep: true } : n));
    return [...before, ...added, ...after.map((n, i) => (i === 0 ? { ...n, sep: true } : n))];
}

export function itemMenu<T extends ItemMenuType>(type: T, ctx: ItemMenuContexts[T], env: ItemMenuEnv): BuiltItemMenu | null {
    const entry = types.get(type) as ItemMenuTypeEntry<ItemMenuContexts[T]> | undefined;
    if (!entry) throw new ItemMenuError(`item menu type "${type}" is not defined`);
    const built = entry.build(ctx, env);
    if (!built) return null;
    const list = (contributions.get(type) ?? []) as ItemMenuContribution<ItemMenuContexts[T]>[];
    return { ...built, nodes: mergeContributions(built.nodes, list.map((c) => closing(c.nodes(ctx, env), env.close))) };
}

export function definedItemMenuTypes(): ItemMenuType[] {
    return [...types.keys()];
}
