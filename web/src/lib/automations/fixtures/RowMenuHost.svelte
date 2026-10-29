
<script lang="ts">
  import RowMenu from '../RowMenu.svelte';

  let { onPick }: { onPick: (action: string) => void } = $props();
  let menu = $state<{ id: string; anchor: HTMLElement } | null>(null);
</script>

<button data-base-exempt="test fixture host, not shipped UI" type="button" data-kebab onclick={(e) => (menu = { id: 'a', anchor: e.currentTarget })}>menu</button>
<button data-base-exempt="test fixture host, not shipped UI" type="button" data-outside>outside</button>
{#if menu}<RowMenu anchor={menu.anchor} {onPick} onClose={() => (menu = null)} />{/if}
