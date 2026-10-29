<!-- hidden -->
<script lang="ts">
  import { Collapsible } from 'bits-ui';
  import type { Snippet } from 'svelte';
  import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';

  interface Props {
    label: string;
    count?: number | string;
    open?: boolean;
    disabled?: boolean;
    onOpenChange?: (open: boolean) => void;
    actions?: Snippet;
    children: Snippet;
  }

  let { label, count, open = $bindable(false), disabled = false, onOpenChange, actions, children }: Props = $props();
</script>

<Collapsible.Root class="oc-fold" bind:open {disabled} {onOpenChange}>
  <div class="oc-fold__head">
    <Collapsible.Trigger class="oc-fold__toggle" data-btn="row">
      <span class="oc-fold__label">{label}</span>
      {#if count !== undefined}<span class="oc-fold__count">{count}</span>{/if}
      <FoldChevron />
    </Collapsible.Trigger>
    {#if actions}<span class="oc-fold__actions">{@render actions()}</span>{/if}
  </div>
  <Collapsible.Content class="oc-fold__panel">{@render children()}</Collapsible.Content>
</Collapsible.Root>
