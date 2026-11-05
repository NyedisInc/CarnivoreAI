import { ACTIONS } from '../../../../client/js/keymap/actions.js';
import { formatChord } from '../../../../client/js/keymap/chord.js';
import { capRows, chordsOf, conflicts, searchText } from '../../../../client/js/keymap/effective.js';
import { buildTree } from '../../../../client/js/keymap/tree.js';
import { leafCount, type TreeNode } from '../base/Tree.svelte';
import type { KeymapOverrides } from './keymap-overrides';

export type KeyboardFamily = 'mac' | 'other';

export interface KeymapAction {
    readonly id: string;
    readonly labelKey: string;
    readonly altLabelKeys: readonly string[];
    readonly category: string;
    readonly scope: string;
    readonly mouse: readonly string[];
    readonly rebindable: boolean;
    readonly fixedKey: string;
    readonly mayShare: boolean;
    readonly keys: { readonly mac: readonly string[]; readonly other: readonly string[] };
}

export interface KeymapLeaf {
    action: KeymapAction;
    itemId?: string;
}

export interface ViewQuery {
    text: string;
    pressed: string | null;
    family: KeyboardFamily;
    t: (key: string) => string;
    overrides?: KeymapOverrides;
}

export interface ViewTree {
    nodes: TreeNode[];
    total: number;
    searching: boolean;
}

const ALL = ACTIONS as unknown as readonly KeymapAction[];

interface RegistryNode {
    id: string;
    labelKey: string;
    children?: RegistryNode[];
    action?: KeymapAction;
    itemId?: string;
}

function leafMatches(leaf: RegistryNode, trail: string[], q: ViewQuery): boolean {
    const action = leaf.action as KeymapAction;
    if (q.pressed) return (chordsOf(action, q.family, q.overrides) as string[]).includes(q.pressed);
    const words = q.text.toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length === 0) return true;
    const chords = (chordsOf(action, q.family, q.overrides) as string[]).map((c) => formatChord(c) as string).join(' ');
    const own = leaf.itemId ? `${q.t(leaf.labelKey)} ${chords}` : `${q.t(leaf.labelKey)} ${searchText(action, q.family, q.t, q.overrides)}`;
    const text = `${trail.join(' ')} ${own}`.toLowerCase();
    return words.every((w) => text.includes(w));
}

function convert(node: RegistryNode, q: ViewQuery, trail: string[]): TreeNode | null {
    const label = q.t(node.labelKey);
    if (!node.children) {
        return node.action && leafMatches(node, trail, q) ? { id: node.id, label, data: { action: node.action, itemId: node.itemId } satisfies KeymapLeaf } : null;
    }
    const children = node.children.map((c) => convert(c, q, [...trail, label])).filter((c): c is TreeNode => c !== null);
    return children.length > 0 ? { id: node.id, label, children } : null;
}

export function viewTree(query: ViewQuery): ViewTree {
    const roots = buildTree(ALL) as RegistryNode[];
    const nodes = roots.map((n) => convert(n, query, [])).filter((n): n is TreeNode => n !== null);
    return { nodes, total: nodes.reduce((n, node) => n + leafCount(node), 0), searching: query.pressed !== null || query.text.trim() !== '' };
}

export function keycapRows(action: KeymapAction, family: KeyboardFamily, overrides?: KeymapOverrides): string[][] {
    return capRows(action, family, overrides) as string[][];
}

export function clashingIds(family: KeyboardFamily, overrides?: KeymapOverrides): Set<string> {
    return new Set((conflicts(ALL, family, overrides) as { a: string; b: string }[]).flatMap((c) => [c.a, c.b]));
}

export function scopeTagKey(scope: string): string {
    return `keymap.scope.${scope.replace(':', '.')}`;
}

export function gestureLabelKey(gesture: string): string {
    return `keymap.gesture.${gesture.replace('+', '_')}`;
}

export const ALL_ACTIONS: readonly KeymapAction[] = ALL;
