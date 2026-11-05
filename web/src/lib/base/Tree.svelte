
<script lang="ts" module>
  export interface TreeNode {
    id: string;
    label: string;
    count?: number;
    children?: readonly TreeNode[];
    data?: unknown;
  }

  export function leafCount(node: TreeNode): number {
    return node.children ? node.children.reduce((n, c) => n + leafCount(c), 0) : 1;
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';

  interface Props extends Omit<HTMLAttributes<HTMLUListElement>, 'class' | 'children' | 'role'> {
    nodes: readonly TreeNode[];
    leaf: Snippet<[TreeNode]>;
    actions?: Snippet<[TreeNode]>;
    label: string;
    open?: Record<string, boolean>;
    defaultOpen?: (node: TreeNode, level: number) => boolean;
    forceOpen?: boolean;
    onActivate?: (node: TreeNode) => void;
  }

  let { nodes, leaf, actions, label, open = $bindable({}), defaultOpen = (_n, level) => level === 1, forceOpen = false, onActivate, ...rest }: Props = $props();

  let root = $state<HTMLUListElement | undefined>();
  let stop = $state<string | null>(null);

  $effect(() => {
    void [nodes, open, forceOpen];
    if (root && stop && !root.querySelector(`[data-tree-item="${CSS.escape(stop)}"]`)) stop = null;
  });

  const isOpen = (node: TreeNode, level: number): boolean => forceOpen || (open[node.id] ?? defaultOpen(node, level));

  let typed = '';
  let typedAt = 0;
  const TYPE_AHEAD_MS = 700;

  function typeAhead(key: string, list: HTMLElement[], at: number): void {
    const now = Date.now();
    typed = now - typedAt > TYPE_AHEAD_MS ? key : typed + key;
    typedAt = now;
    const word = typed.toLowerCase();
    const from = typed.length === 1 ? at + 1 : at;
    const order = [...list.slice(from), ...list.slice(0, from)];
    focusItem(order.find((el) => (el.dataset.treeLabel ?? '').toLowerCase().startsWith(word)));
  }

  const items = (): HTMLElement[] => (root ? [...root.querySelectorAll<HTMLElement>('[data-tree-item]')] : []);

  function toggle(node: TreeNode, level: number): void {
    if (!forceOpen) open = { ...open, [node.id]: !isOpen(node, level) };
  }

  function focusItem(el: HTMLElement | undefined): void {
    if (!el) return;
    stop = el.dataset.treeItem ?? null;
    el.focus();
  }

  function onKey(event: KeyboardEvent): void {
    const target = event.target as HTMLElement;
    if (!target.matches('[data-tree-item]') || event.altKey || event.ctrlKey || event.metaKey) return;
    const list = items();
    const at = list.indexOf(target);
    const branch = target.dataset.treeBranch === 'true';
    const level = Number(target.getAttribute('aria-level'));
    const expanded = target.getAttribute('aria-expanded') === 'true';
    const node = find(nodes, target.dataset.treeItem ?? '');
    let handled = true;
    if (event.key === 'ArrowDown') focusItem(list[at + 1]);
    else if (event.key === 'ArrowUp') focusItem(list[at - 1]);
    else if (event.key === 'Home') focusItem(list[0]);
    else if (event.key === 'End') focusItem(list[list.length - 1]);
    else if (event.key === 'ArrowRight' && branch && !expanded && node) toggle(node, level);
    else if (event.key === 'ArrowRight' && branch && expanded) focusItem(list[at + 1]);
    else if (event.key === 'ArrowLeft' && branch && expanded && node) toggle(node, level);
    else if (event.key === 'ArrowLeft') focusItem([...list.slice(0, at)].reverse().find((el) => Number(el.getAttribute('aria-level')) < level));
    else if (event.key.length === 1 && event.key !== ' ') typeAhead(event.key, list, at);
    else if ((event.key === 'Enter' || event.key === ' ') && node) {
      if (branch) toggle(node, level);
      else onActivate?.(node);
    } else handled = false;
    if (handled) event.preventDefault();
  }

  function find(list: readonly TreeNode[], id: string): TreeNode | undefined {
    for (const n of list) {
      if (n.id === id) return n;
      const inner = n.children ? find(n.children, id) : undefined;
      if (inner) return inner;
    }
    return undefined;
  }
</script>

{#snippet level(list: readonly TreeNode[], depth: number)}
  {#each list as node (node.id)}
    {#if node.children}
      {@const expanded = isOpen(node, depth)}
      <li role="none">
        <div
          class="oc-tree__row oc-tree__branch"
          role="treeitem"
          aria-level={depth}
          aria-expanded={expanded}
          tabindex={(stop ?? nodes[0]?.id) === node.id ? 0 : -1}
          data-tree-item={node.id}
          data-tree-label={node.label}
          data-tree-branch="true"
          style:--_oc-tree-depth={depth - 1}
          onclick={() => toggle(node, depth)}
          onfocus={() => (stop = node.id)}
        >
          <FoldChevron />
          <span class="oc-tree__label">{node.label}</span>
          <span class="oc-tree__count">{node.count ?? leafCount(node)}</span>
        </div>
        {#if expanded}
          <ul role="group" class="oc-tree__group">{@render level(node.children, depth + 1)}</ul>
        {/if}
      </li>
    {:else}
      <li role="none" class="oc-tree__line">
        <div
          class="oc-tree__row oc-tree__leaf"
          role="treeitem"
          aria-level={depth}
          aria-selected="false"
          tabindex={(stop ?? nodes[0]?.id) === node.id ? 0 : -1}
          data-tree-item={node.id}
          data-tree-label={node.label}
          style:--_oc-tree-depth={depth - 1}
          onfocus={() => (stop = node.id)}
        >
          {@render leaf(node)}
        </div>
        {#if actions}<div class="oc-tree__actions">{@render actions(node)}</div>{/if}
      </li>
    {/if}
  {/each}
{/snippet}

<ul {...rest} bind:this={root} class="oc-tree" role="tree" aria-label={label} onkeydown={onKey}>
  {@render level(nodes, 1)}
</ul>
