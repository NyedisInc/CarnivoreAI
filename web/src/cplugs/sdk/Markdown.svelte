<script lang="ts">
  import { markdownKit } from './markdown';

  let { text, inline = false }: { text: string; inline?: boolean } = $props();
  const Block = markdownKit()?.Block;
</script>

{#if Block}<Block {text} {inline} />{:else}{text}{/if}
