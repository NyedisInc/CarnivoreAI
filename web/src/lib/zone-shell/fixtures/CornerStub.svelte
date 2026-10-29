<script lang="ts">
  import type { Snippet } from 'svelte';

  let { corner = null }: { corner?: Snippet | null } = $props();
</script>

<div data-corner-stub>{#if corner}{@render corner()}{/if}</div>
