
<script lang="ts">
  import Button from './Button.svelte';

  let { state }: { state: { flag: boolean; items: string[] } } = $props();
</script>

<Button>{#if state.flag}<b data-if>flagged{' '}</b>{/if}{#each state.items as item (item)}<i data-item>{item}{' '}</i>{/each}</Button>
