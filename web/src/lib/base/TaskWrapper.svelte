
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { nextTaskState, partsOf, type TaskPart, type TaskState } from './task-wrapper';

  interface Props {
    state: TaskState;
    onStateChange?: (next: TaskState) => void;
    as?: 'li' | 'div';
    toggleProps?: Record<string, string | number | boolean | undefined>;
    lead?: Snippet;
    head: Snippet;
    keys?: Snippet;
    tabs?: Snippet;
    class?: string;
    [attribute: string]: unknown;
  }

  let { state, onStateChange, as = 'div', toggleProps = {}, lead, head, keys, tabs, class: extra = '', ...rest }: Props = $props();

  function hideWhenEmpty(node: HTMLElement): { destroy: () => void } {
    const sync = (): void => { node.hidden = node.childElementCount === 0; };
    sync();
    const watcher = new MutationObserver(sync);
    watcher.observe(node, { childList: true });
    return { destroy: () => watcher.disconnect() };
  }

  const parts = $derived<readonly TaskPart[]>(partsOf(state));
  const expanded = $derived(state !== 'compact');
</script>

<svelte:element this={as} class="oc-task {extra}" data-oc-base data-task-state={state} {...rest}>
  <div class="oc-task__row">
    {#if lead}{@render lead()}{/if}
    <button type="button" class="oc-task__toggle" aria-expanded={expanded} {...toggleProps} onclick={() => onStateChange?.(nextTaskState(state))}>{@render head()}</button>
    {#if keys}<span class="oc-task__keys">{@render keys()}</span>{/if}
  </div>
  {#if tabs && parts.includes('tabs')}<div class="oc-task__tabs" data-task-part="tabs" use:hideWhenEmpty>{@render tabs()}</div>{/if}
</svelte:element>
