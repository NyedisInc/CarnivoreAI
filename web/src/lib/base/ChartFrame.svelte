<!-- padding -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    size?: 'tile' | 'panel' | 'full';
    label?: string;
    busy?: boolean;
    element?: HTMLElement | undefined;
    class?: string;
    children: Snippet;
  }

  let { size = 'panel', label, busy = false, element = $bindable(), class: extra = '', children }: Props = $props();
</script>

<section bind:this={element} class="oc-chart-frame oc-chart-frame--{size} {extra}" aria-busy={busy} aria-label={label}>{@render children()}</section>
