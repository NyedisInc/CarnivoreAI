/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import Tree, { type TreeNode } from './Tree.svelte';

if (typeof CSS === 'undefined') (globalThis as { CSS?: unknown }).CSS = {};
if (!CSS.escape) CSS.escape = (v: string): string => v.replace(/[^\w-]/g, (c) => `\\${c}`);

const NODES: TreeNode[] = [{ id: 'g', label: 'group', children: [{ id: 'a', label: 'alpha' }, { id: 'b', label: 'beta' }, { id: 'bb', label: 'bravo' }] }];
let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function show(): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    const leaf = createRawSnippet((node: () => TreeNode) => ({ render: () => `<span>${node().label}</span>` }));
    const actions = createRawSnippet((node: () => TreeNode) => ({ render: () => `<button data-act="${node().id}">go</button>` }));
    handle = mount(Tree, { target, props: { nodes: NODES, leaf, actions, label: 'tree' } });
    flushSync();
    return target;
}

const key = (el: Element, k: string): void => {
    el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
    flushSync();
};
const item = (host: HTMLElement, id: string): HTMLElement => host.querySelector<HTMLElement>(`[data-tree-item="${id}"]`)!;

test('typing letters jumps to the next visible item whose label starts with them', () => {
    const host = show();
    item(host, 'g').focus();
    key(item(host, 'g'), 'b');
    expect(document.activeElement).toBe(item(host, 'b'));
    key(item(host, 'b'), 'r');
    expect(document.activeElement).toBe(item(host, 'bb'));
});

test('a leaf actions cell is outside the treeitem', () => {
    const host = show();
    expect(host.querySelector('[data-act="a"]')).not.toBeNull();
    expect(host.querySelector('[role="treeitem"] [data-act]')).toBeNull();
});
