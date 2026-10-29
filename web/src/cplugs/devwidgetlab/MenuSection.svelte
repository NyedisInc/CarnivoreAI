<script lang="ts">
  import type { Snippet } from 'svelte';
  import { FoldChevron } from '../sdk/ui';

  interface Props {
    label: string;
    value: string;
    tone?: 'warn' | 'bad' | undefined;
    open: boolean;
    ontoggle: (open: boolean) => void;
    children: Snippet;
  }

  const { label, value, tone, open, ontoggle, children }: Props = $props();
</script>

<section class="dwl-sec" data-open={open ? 'yes' : 'no'}>
  <button type="button" class="dwl-group dwl-sec-head" aria-expanded={open} onclick={() => ontoggle(!open)}>
    <FoldChevron />
    <span class="dwl-sec-label">{label}</span>
    <span class="dwl-sec-value" data-tone={tone}>{value}</span>
  </button>
  {#if open}<div class="dwl-sec-body">{@render children()}</div>{/if}
</section>
