
<script lang="ts">
  import IconButton from './IconButton.svelte';

  let { seen }: { seen: { el: HTMLElement | null } } = $props();
  let element: HTMLElement | null = $state(null);

  $effect(() => {
    seen.el = element;
  });
</script>

<IconButton label="open" icon="plus" bind:element />
