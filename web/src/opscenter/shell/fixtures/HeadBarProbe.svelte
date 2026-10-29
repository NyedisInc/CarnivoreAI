<script lang="ts">
  import { framedTitle, useHeaderGroup } from '../frame-header.svelte';

  const place = useHeaderGroup(() => bar);
  const framing = framedTitle();
</script>

{#snippet bar()}
  <button type="button" data-probe-bar="">bar</button>
{/snippet}

<div data-probe-body="">
  {#if !framing.on}<strong data-probe-name="">probe</strong>{/if}
  {#if !place.up}{@render bar()}{/if}
</div>
