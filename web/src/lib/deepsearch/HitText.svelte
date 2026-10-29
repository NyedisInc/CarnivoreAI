<script lang="ts">
  import { snippetParts } from '../conversation-snippet/snippet-parts';

  interface Props {
    snippet: string;
  }
  let { snippet }: Props = $props();
  const parts = $derived(snippetParts(snippet));
</script>

{#each parts as part, i (i)}{#if part.match}<mark class="sd-mark">{part.text}</mark>{:else}{part.text}{/if}{/each}
