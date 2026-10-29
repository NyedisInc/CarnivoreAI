<script lang="ts">
  import { useFrameHeader } from '../frame-header.svelte';

  const frameHeader = useFrameHeader();
  const up = $derived(!!frameHeader?.drawn);
  $effect(() => {
    if (!frameHeader || !up) return;
    frameHeader.content = ownHead;
    return () => {
      if (frameHeader.content === ownHead) frameHeader.content = null;
    };
  });
</script>

{#snippet ownHead()}
  <span data-probe-own-head="">own head</span>
{/snippet}

{#if !up}{@render ownHead()}{/if}
