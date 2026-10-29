
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import type { ListDensity } from './List.svelte';

  interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'class' | 'children'> {
    primary?: string | Snippet;
    secondary?: string | Snippet;
    meta?: string | Snippet;
    lead?: Snippet;
    actions?: Snippet;
    below?: Snippet;
    children?: Snippet;
    selected?: boolean;
    wrap?: boolean;
    density?: ListDensity;
    role?: string;
    class?: string;
  }

  let {
    primary, secondary, meta, lead, actions, below, children, selected = false, wrap = false, density, role = 'listitem', class: extra = '', ...rest
  }: Props = $props();
</script>

{#snippet part(value: string | Snippet)}{#if typeof value === 'string'}{value}{:else}{@render value()}{/if}{/snippet}

{#snippet parts()}
  {#if children}
    {@render children()}
  {:else}
    {#if lead}<span class="oc-list__lead">{@render lead()}</span>{/if}
    <span class="oc-list__main">
      {#if primary !== undefined}<span class="oc-list__primary">{@render part(primary)}</span>{/if}
      {#if secondary !== undefined}<span class="oc-list__secondary">{@render part(secondary)}</span>{/if}
    </span>
    {#if meta !== undefined}<span class="oc-list__meta">{@render part(meta)}</span>{/if}
  {/if}
  {#if actions}<span class="oc-list__actions">{@render actions()}</span>{/if}
{/snippet}

<div
  {...rest}
  class={['oc-list__row', extra]}
  {role}
  data-density={density}
  data-selected={selected || undefined}
  data-wrap={wrap || undefined}
  data-below={below ? '' : undefined}
  data-interactive={rest.onclick && rest['aria-disabled'] !== 'true' && rest['aria-disabled'] !== true ? '' : undefined}
>
  {#if below}
    <span class="oc-list__head">{@render parts()}</span>
    <span class="oc-list__below">{@render below()}</span>
  {:else}
    {@render parts()}
  {/if}
</div>
