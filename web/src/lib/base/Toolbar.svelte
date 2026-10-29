<!-- <input data-field type="search" /> padding -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { scrollFade } from '../../opscenter/ui/scroll-fade';

  interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'class' | 'children'> {
    search?: Snippet;
    filters?: Snippet;
    extras?: Snippet;
    end?: Snippet;
    below?: Snippet;
    band?: boolean;
    wrap?: boolean;
    label?: string;
    role?: string;
    class?: string;
  }

  let {
    search, filters, extras, end, below, band = false, wrap = false, label, role = 'toolbar', class: extra = '', ...rest
  }: Props = $props();
</script>

<div
  {...rest}
  class={['oc-toolbar', band && 'oc-toolbar--band', wrap && 'oc-toolbar--wrap', extra]}
  {role}
  aria-label={label}
  use:scrollFade
>
  {#if search}<div class="oc-toolbar__search">{@render search()}</div>{/if}
  {#if filters}<div class="oc-toolbar__facets">{@render filters()}</div>{/if}
  {#if extras}<div class="oc-toolbar__extras" use:scrollFade>{@render extras()}</div>{/if}
  {#if end}<div class="oc-toolbar__end">{@render end()}</div>{/if}
  {#if below}<div class="oc-toolbar__below">{@render below()}</div>{/if}
</div>
